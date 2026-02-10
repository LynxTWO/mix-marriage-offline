.PHONY: validate test ui-validate

validate:
	python tools/validate_contracts.py

test:
	PYTHONPATH=src python -m pytest -q

ui-validate:
	python tools/validate_ui_specs.py
	python tools/validate_ui_examples.py
