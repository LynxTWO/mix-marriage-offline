import { invoke } from "@tauri-apps/api/core";

window.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector<HTMLFormElement>("#runtime-check-form");
  const nameInput = document.querySelector<HTMLInputElement>("#runtime-check-name");
  const message = document.querySelector<HTMLElement>("#runtime-check-message");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!nameInput || !message) {
      return;
    }

    const name = nameInput.value.trim() || "operator";
    form.setAttribute("aria-busy", "true");

    try {
      message.textContent = await invoke("greet", { name });
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      message.textContent = `Rust invocation failed: ${detail}`;
    } finally {
      form.removeAttribute("aria-busy");
    }
  });
});
