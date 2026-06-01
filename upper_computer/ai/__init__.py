"""AI 辅助研判模块。"""

try:
    from .judgement import (
        AISettings,
        LocalJinaRuntime,
        fetch_llm_models,
        fetch_llm_models_result,
        load_ai_settings,
        run_ai_judgement,
        save_ai_settings,
        settings_from_dict,
        test_embedding,
        test_llm,
        test_llm_result,
        wait_for_embedding_ready,
    )
except ImportError:  # 兼容 cd upper_computer 后直接 python main.py
    from judgement import (  # type: ignore
        AISettings,
        LocalJinaRuntime,
        fetch_llm_models,
        fetch_llm_models_result,
        load_ai_settings,
        run_ai_judgement,
        save_ai_settings,
        settings_from_dict,
        test_embedding,
        test_llm,
        test_llm_result,
        wait_for_embedding_ready,
    )

__all__ = [
    "AISettings",
    "LocalJinaRuntime",
    "fetch_llm_models",
    "fetch_llm_models_result",
    "load_ai_settings",
    "run_ai_judgement",
    "save_ai_settings",
    "settings_from_dict",
    "test_embedding",
    "test_llm",
    "test_llm_result",
    "wait_for_embedding_ready",
]
