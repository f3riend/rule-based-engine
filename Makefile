run:
	uv run uvicorn main:app --reload

listener:
	uv run python listener.py

workflow-worker:
	uv run python workflow_worker.py

crewai-worker:
	uv run python crewai_worker.py

test-api:
	uv run python test_api.py

test-full:
	uv run python full_system_test.py
	@echo "Rapor: full_system_test_results.txt"

seed-data:
	uv run python fake_data_generator.py

simulate:
	uv run python business_activity_simulator.py

rules-preview:
	uv run python rule_manager.py preview "$(TEXT)"

rules-apply:
	uv run python rule_manager.py apply "$(TEXT)"

rules-validate:
	uv run python rule_manager.py validate

dashboard:
	@echo "Open http://127.0.0.1:8000/api/internal/dashboard"