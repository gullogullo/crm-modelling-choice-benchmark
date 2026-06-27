SOURCE_DIR ?= data/external/board-pilot-data-762213835c6c6cdd20fcadb4ded90119ae3ee147

.PHONY: fetch run analysis figure pdf test clean

fetch:
	python3 fetch_source.py

run:
	python3 run_experiment.py --source-dir "$(SOURCE_DIR)" --output-dir outputs
	python3 analyse_outputs.py
	python3 generate_single_record_figure.py

analysis:
	python3 analyse_outputs.py

figure:
	python3 generate_single_record_figure.py

pdf:
	@command -v rsvg-convert >/dev/null || { echo "rsvg-convert is required for PDF export"; exit 1; }
	rsvg-convert -f pdf -o outputs/analysis/per_record_answer_composition.pdf outputs/analysis/per_record_answer_composition.svg
	rsvg-convert -f pdf -o outputs/analysis/documented_answer_space.pdf outputs/analysis/documented_answer_space.svg
	rsvg-convert -f pdf -o figures/single_record_shortcut_comparison.pdf figures/single_record_shortcut_comparison.svg

test:
	python3 -m unittest discover -s tests -v

clean:
	rm -rf outputs
