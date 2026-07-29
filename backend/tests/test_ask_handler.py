"""Tests for question classification and entity extraction."""
import pytest
from app.api.ask_handler import classify_question


def test_classify_metric_sql_factual():
    q_type, handler = classify_question("GMV最新值是多少")
    assert handler == "metric_sql"


def test_classify_metric_sql_ranking():
    q_type, handler = classify_question("各品类毛利率排名")
    assert handler == "metric_sql"


def test_classify_metric_sql_comparison():
    q_type, handler = classify_question("肉类和水产GMV对比")
    assert handler == "metric_sql"


def test_classify_metric_sql_trend():
    q_type, handler = classify_question("总体GMV最近5周趋势")
    assert handler == "metric_sql"


def test_classify_analytical():
    q_type, handler = classify_question("为什么复购率下降了")
    assert handler == "llm_analytical"


def test_classify_what_if():
    q_type, handler = classify_question("如果客单价提高10%会怎样")
    assert handler == "python_what_if"


def test_classify_general_fallback():
    q_type, handler = classify_question("你好，讲个笑话")
    assert handler == "llm_general"
