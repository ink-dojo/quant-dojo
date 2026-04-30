PYTHON ?= python
PIP ?= pip
NPM ?= npm

.PHONY: help health test portfolio-data portfolio-dev portfolio-build portfolio-clean \
        hero-analysis coverage-audit install-hooks

help:
	@echo "quant-dojo · Makefile"
	@echo ""
	@echo "  Portfolio site (portfolio/)"
	@echo "  ───────────────────────────"
	@echo "  portfolio-data      python3 scripts/export_data.py (66 factors + hero + strategy + live + journey)"
	@echo "  portfolio-dev       next dev on :3000 (auto prebuild exports data first)"
	@echo "  portfolio-build     SSG build → portfolio/out/"
	@echo "  portfolio-clean     rm -rf portfolio/out portfolio/.next"
	@echo ""
	@echo "  Research pipelines"
	@echo "  ───────────────────"
	@echo "  health              offline smoke: imports + key tests + doctor"
	@echo "  test                full pytest regression"
	@echo "  coverage-audit      scripts/audit_factor_data_coverage.py → journal/portfolio_factor_coverage.json"
	@echo "  hero-analysis       scripts/deep_analysis_hero_factors.py → journal/hero_factor_stats_YYYYMMDD.json (~10 min)"
	@echo ""
	@echo "  Automation"
	@echo "  ──────────"
	@echo "  install-hooks       install .githooks/post-commit to .git/hooks (auto-regen portfolio data)"

# ── Portfolio site ────────────────────────────────────────────────────────

portfolio-data:
	cd portfolio && $(PYTHON) scripts/export_data.py

portfolio-dev: portfolio-data
	cd portfolio && npm run dev

portfolio-build:
	cd portfolio && $(NPM) install && $(NPM) run build

portfolio-clean:
	rm -rf portfolio/out portfolio/.next

# ── Research pipelines ────────────────────────────────────────────────────

health:
	$(PYTHON) -c "from utils import get_stock_history; from agents import LLMClient; print('imports ok')"
	$(PYTHON) -m pytest agents/test_debate.py tests/test_live_data.py tests/test_vol_targeting.py tests/pipeline/test_capacity_monitor.py tests/scripts/test_stress_test.py tests/test_live_vs_backtest_divergence.py tests/test_event_kill_switch.py -q
	$(PYTHON) -m quant_dojo doctor

test:
	$(PYTHON) -m pytest -q

coverage-audit:
	$(PYTHON) scripts/audit_factor_data_coverage.py

hero-analysis:
	$(PYTHON) scripts/deep_analysis_hero_factors.py

# ── Automation ────────────────────────────────────────────────────────────

install-hooks:
	@mkdir -p .git/hooks
	@cp .githooks/post-commit .git/hooks/post-commit
	@chmod +x .git/hooks/post-commit
	@echo "✅ post-commit hook installed → .git/hooks/post-commit"
	@echo "   (will auto-regen portfolio/public/data/* when alpha_factors.py, ROADMAP.md, or live/ changes)"
