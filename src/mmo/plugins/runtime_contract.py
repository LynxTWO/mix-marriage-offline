"""Runtime purity guardrails for plugin execution."""

from __future__ import annotations

import importlib
import random
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Iterator, TypeVar
from unittest import mock

from mmo.plugins.interfaces import PluginPurityContract

_T = TypeVar("_T")

_DEFAULT_PURITY = PluginPurityContract(
    audio_buffer="typed_f64_interleaved",
    randomness="forbidden",
    wall_clock="forbidden",
    thread_scheduling="forbidden",
)


class PluginPurityViolationError(RuntimeError):
    """Raised when a plugin violates the declared determinism purity contract."""


def normalize_purity_contract(value: Any) -> PluginPurityContract:
    if isinstance(value, PluginPurityContract):
        return PluginPurityContract(
            audio_buffer=value.audio_buffer or _DEFAULT_PURITY.audio_buffer,
            randomness=value.randomness or _DEFAULT_PURITY.randomness,
            wall_clock=value.wall_clock or _DEFAULT_PURITY.wall_clock,
            thread_scheduling=(
                value.thread_scheduling or _DEFAULT_PURITY.thread_scheduling
            ),
        )
    return _DEFAULT_PURITY


def purity_contract_from_capabilities(
    capabilities: Any,
    *,
    deterministic_seed_policy: str | None = None,
) -> PluginPurityContract | None:
    raw_purity: Any = None
    effective_seed_policy = deterministic_seed_policy
    if isinstance(capabilities, dict):
        raw_purity = capabilities.get("purity")
        if effective_seed_policy is None:
            seed_value = capabilities.get("deterministic_seed_policy")
            if isinstance(seed_value, str) and seed_value.strip():
                effective_seed_policy = seed_value.strip()
    else:
        raw_purity = getattr(capabilities, "purity", None)
        if effective_seed_policy is None:
            seed_value = getattr(capabilities, "deterministic_seed_policy", None)
            if isinstance(seed_value, str) and seed_value.strip():
                effective_seed_policy = seed_value.strip()

    if isinstance(raw_purity, PluginPurityContract):
        return normalize_purity_contract(raw_purity)
    if not isinstance(raw_purity, dict):
        return None

    randomness = raw_purity.get("randomness")
    if not isinstance(randomness, str) or not randomness.strip():
        if effective_seed_policy in {"seed_required", "seed_optional"}:
            randomness = "process_context_seed"
        elif effective_seed_policy == "none":
            randomness = "forbidden"
        else:
            randomness = None

    return normalize_purity_contract(
        PluginPurityContract(
            audio_buffer=(
                raw_purity.get("audio_buffer").strip()
                if isinstance(raw_purity.get("audio_buffer"), str)
                and raw_purity.get("audio_buffer").strip()
                else None
            ),
            randomness=(
                randomness.strip()
                if isinstance(randomness, str) and randomness.strip()
                else None
            ),
            wall_clock=(
                raw_purity.get("wall_clock").strip()
                if isinstance(raw_purity.get("wall_clock"), str)
                and raw_purity.get("wall_clock").strip()
                else None
            ),
            thread_scheduling=(
                raw_purity.get("thread_scheduling").strip()
                if isinstance(raw_purity.get("thread_scheduling"), str)
                and raw_purity.get("thread_scheduling").strip()
                else None
            ),
        )
    )


def _violation(plugin_id: str, detail: str) -> None:
    raise PluginPurityViolationError(
        f"{plugin_id} violated determinism purity contract: {detail}",
    )


def _build_random_patches(
    *,
    plugin_id: str,
    purity: PluginPurityContract,
) -> list[Any]:
    patched: list[Any] = []
    original_random_class = random.Random

    def _seed_or_violation(*args: Any, keyword: str = "seed", **kwargs: Any) -> Any:
        seed = args[0] if args else kwargs.get(keyword)
        if seed is None:
            _violation(
                plugin_id,
                "deterministic RNG constructors require an explicit seed from process_ctx.seed.",
            )
        return seed

    if purity.randomness == "process_context_seed":
        import numpy as np

        original_default_rng = np.random.default_rng
        original_random_state = np.random.RandomState
        original_bit_generator_ctors = {
            name: getattr(np.random, name)
            for name in ("PCG64", "MT19937", "Philox", "SFC64")
        }

        def guarded_random_ctor(*args: Any, **kwargs: Any) -> random.Random:
            _seed_or_violation(*args, keyword="x", **kwargs)
            return original_random_class(*args, **kwargs)

        def guarded_default_rng(*args: Any, **kwargs: Any) -> Any:
            seed = _seed_or_violation(*args, keyword="seed", **kwargs)
            return np.random.Generator(original_bit_generator_ctors["PCG64"](seed))

        def guarded_random_state(*args: Any, **kwargs: Any) -> Any:
            seed = _seed_or_violation(*args, keyword="seed", **kwargs)
            return original_random_state(seed)

        def guarded_bit_generator_ctor(name: str) -> Callable[..., Any]:
            def _ctor(*args: Any, **kwargs: Any) -> Any:
                seed = _seed_or_violation(*args, keyword="seed", **kwargs)
                original_ctor = original_bit_generator_ctors[name]
                return original_ctor(seed)

            return _ctor

        patched.extend(
            [
                mock.patch("random.Random", new=guarded_random_ctor),
                mock.patch("numpy.random.default_rng", new=guarded_default_rng),
                mock.patch("numpy.random.RandomState", new=guarded_random_state),
                mock.patch("numpy.random.PCG64", new=guarded_bit_generator_ctor("PCG64")),
                mock.patch("numpy.random.MT19937", new=guarded_bit_generator_ctor("MT19937")),
                mock.patch("numpy.random.Philox", new=guarded_bit_generator_ctor("Philox")),
                mock.patch("numpy.random.SFC64", new=guarded_bit_generator_ctor("SFC64")),
            ]
        )

    if purity.randomness not in {"forbidden", "process_context_seed"}:
        return patched

    def forbidden_random(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        _violation(
            plugin_id,
            "global RNG helpers are forbidden; derive deterministic behavior from process_ctx.seed.",
        )

    module_level_random_names = (
        "betavariate",
        "choice",
        "choices",
        "expovariate",
        "gammavariate",
        "gauss",
        "getrandbits",
        "lognormvariate",
        "normalvariate",
        "paretovariate",
        "randint",
        "random",
        "randrange",
        "sample",
        "seed",
        "shuffle",
        "triangular",
        "uniform",
        "vonmisesvariate",
    )
    for name in module_level_random_names:
        patched.append(mock.patch(f"random.{name}", forbidden_random))

    def forbidden_system_random(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        _violation(
            plugin_id,
            "random.SystemRandom is forbidden for deterministic plugins.",
        )

    patched.append(mock.patch("random.SystemRandom", new=forbidden_system_random))

    if purity.randomness == "forbidden":
        def forbidden_random_ctor(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            _violation(
                plugin_id,
                "random.Random is forbidden unless the manifest explicitly allows process_ctx.seed-based RNG.",
            )

        def forbidden_numpy_ctor(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            _violation(
                plugin_id,
                "numpy RNG constructors are forbidden unless the manifest explicitly allows process_ctx.seed-based RNG.",
            )

        patched.extend(
            [
                mock.patch("random.Random", new=forbidden_random_ctor),
                mock.patch("numpy.random.default_rng", new=forbidden_numpy_ctor),
                mock.patch("numpy.random.RandomState", new=forbidden_numpy_ctor),
                mock.patch("numpy.random.PCG64", new=forbidden_numpy_ctor),
                mock.patch("numpy.random.MT19937", new=forbidden_numpy_ctor),
                mock.patch("numpy.random.Philox", new=forbidden_numpy_ctor),
                mock.patch("numpy.random.SFC64", new=forbidden_numpy_ctor),
            ]
        )

    numpy_random_names = (
        "bytes",
        "choice",
        "permutation",
        "rand",
        "randint",
        "randn",
        "random",
        "random_sample",
        "sample",
        "seed",
        "shuffle",
    )
    for name in numpy_random_names:
        patched.append(mock.patch(f"numpy.random.{name}", forbidden_random))

    return patched


def _build_time_patches(plugin_id: str) -> list[Any]:
    def forbidden_time(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        _violation(
            plugin_id,
            "wall-clock and timer APIs are forbidden inside deterministic plugin execution.",
        )

    return [
        mock.patch("time.monotonic", forbidden_time),
        mock.patch("time.monotonic_ns", forbidden_time),
        mock.patch("time.perf_counter", forbidden_time),
        mock.patch("time.perf_counter_ns", forbidden_time),
        mock.patch("time.process_time", forbidden_time),
        mock.patch("time.process_time_ns", forbidden_time),
        mock.patch("time.sleep", forbidden_time),
        mock.patch("time.thread_time", forbidden_time),
        mock.patch("time.thread_time_ns", forbidden_time),
        mock.patch("time.time", forbidden_time),
        mock.patch("time.time_ns", forbidden_time),
    ]


def _build_thread_patches(plugin_id: str) -> list[Any]:
    def forbidden_thread_start(self: Any, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        _violation(
            plugin_id,
            "spawning threads or executors is forbidden during deterministic plugin execution.",
        )

    def forbidden_executor(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        _violation(
            plugin_id,
            "creating executors is forbidden during deterministic plugin execution.",
        )

    return [
        mock.patch("threading.Thread.start", forbidden_thread_start),
        mock.patch("threading.Timer.start", forbidden_thread_start),
        mock.patch("multiprocessing.Process.start", forbidden_thread_start),
        mock.patch("concurrent.futures.ThreadPoolExecutor", forbidden_executor),
        mock.patch("concurrent.futures.ProcessPoolExecutor", forbidden_executor),
        mock.patch("asyncio.to_thread", forbidden_executor),
        mock.patch("asyncio.AbstractEventLoop.run_in_executor", forbidden_executor),
    ]


@contextmanager
def plugin_purity_guard(
    *,
    plugin_id: str,
    purity_contract: PluginPurityContract | None,
) -> Iterator[None]:
    purity = normalize_purity_contract(purity_contract)
    with ExitStack() as stack:
        if purity.randomness in {"forbidden", "process_context_seed"}:
            # Import lazily-pulled RNG modules before patching random.SystemRandom.
            importlib.import_module("secrets")
            importlib.import_module("numpy.random")
            for patcher in _build_random_patches(plugin_id=plugin_id, purity=purity):
                stack.enter_context(patcher)
        if purity.wall_clock == "forbidden":
            for patcher in _build_time_patches(plugin_id):
                stack.enter_context(patcher)
        if purity.thread_scheduling == "forbidden":
            for patcher in _build_thread_patches(plugin_id):
                stack.enter_context(patcher)
        yield


def invoke_with_purity_guard(
    *,
    plugin_id: str,
    purity_contract: PluginPurityContract | None,
    invoke: Callable[[], _T],
) -> _T:
    with plugin_purity_guard(
        plugin_id=plugin_id,
        purity_contract=purity_contract,
    ):
        return invoke()
