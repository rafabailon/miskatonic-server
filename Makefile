.PHONY: install run test check benchmark clean

install:
	python3 -m pip install -e .

run:
	PYTHONPATH=. python3 -m src.app

test:
	PYTHONPATH=. python3 -m unittest discover -s tests -v

check:
	PYTHONPATH=. python3 -m compileall -q src tests
	PYTHONPATH=. python3 -m unittest discover -s tests -v

benchmark:
	PYTHONPATH=. python3 tests/run_benchmarks.py

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
