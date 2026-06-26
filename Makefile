.PHONY: install test keyboard fetch-ligatus ligatus figures

install:
	python -m pip install -e ".[test]"

test:
	PYTHONPATH=src pytest -q

keyboard:
	PYTHONPATH=src python -m remake_sensitivity.run \
		--config data/e11e81/config.yaml \
		--allow-frozen-rerun

fetch-ligatus:
	PYTHONPATH=src python -m remake_sensitivity.ligatus_fetch \
		--config data/ligatus/board_pilot.yaml \
		--destination data/external/ligatus

ligatus:
	PYTHONPATH=src python -m remake_sensitivity.ligatus_benchmark \
		--config data/ligatus/board_pilot.yaml \
		--data-dir data/external/ligatus/board-pilot-data-762213835c6c6cdd20fcadb4ded90119ae3ee147 \
		--output-root outputs

figures:
	mkdir -p figures/generated
	python figures/prepare_publication_data.py
	set -e; for source in \
		figures/tex/figure01_benchmark_pipeline.tex \
		figures/tex/figure02_current_vs_lineage_query.tex \
		figures/tex/figure03_ordering_policy_sensitivity.tex \
		figures/tex/figure04_example_answer_difference.tex; do \
		pdflatex -interaction=nonstopmode -halt-on-error \
			-output-directory=figures/generated $$source; \
	done
	rm -f figures/generated/*.aux figures/generated/*.log
