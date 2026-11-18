"""TRex 目录探索达标/退出码/清理参数的失败测试（006-T011，US3）。

TDD 红-绿：当前 main.py 尚无达标计数（G1：语法通过 cat_*.py ≥ catalog_target
→ 退出码 0，未达标 → 1 且总结仍落盘）、无 --catalog-target<1 拒绝（G1a）、
无 --clean-scripts 清理参数（G2）。全部用 tmp_path，零流量零 LLM。
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import src.main as main_mod


def _parse(argv: list[str]):
    with patch.object(sys, "argv", ["main.py", *argv]):
        return main_mod.parse_args()


VALID_CODE = "import trex_stl_lib\nprint('ok')\n"
BROKEN_CODE = "def broken(:\n"


# ── G1a：--catalog-target < 1 解析拒绝 ───────────────────────────────

class TestCatalogTargetRejected:
    @pytest.mark.parametrize("target", ["0", "-1"])
    def test_catalog_target_below_one_rejected(self, target):
        with pytest.raises(SystemExit) as excinfo:
            _parse(["--trex-explore", "--catalog-target", target])
        assert excinfo.value.code != 0  # 解析期报错、非 0 退出码（G1a）


# ── G1b：达标计数与退出码 ────────────────────────────────────────────

class TestCatalogSyntaxCounting:
    def _seed(self, tmp_path: Path) -> Path:
        (tmp_path / "cat_ok.py").write_text(VALID_CODE, encoding="utf-8")
        (tmp_path / "cat_bad.py").write_text(BROKEN_CODE, encoding="utf-8")
        (tmp_path / "cat_extra.py").write_text(VALID_CODE, encoding="utf-8")
        # 非 cat_ 前缀：不得参与计数
        (tmp_path / "other.py").write_text(VALID_CODE, encoding="utf-8")
        return tmp_path

    def test_counts_only_syntax_ok_cat_scripts(self, tmp_path):
        self._seed(tmp_path)
        assert main_mod._count_syntax_ok_catalog_scripts(tmp_path) == 2

    def test_missing_dir_counts_zero(self, tmp_path):
        assert main_mod._count_syntax_ok_catalog_scripts(tmp_path / "nope") == 0

    def test_exit_code_zero_when_reached(self):
        assert main_mod._catalog_exit_code(5, 5) == 0
        assert main_mod._catalog_exit_code(6, 5) == 0

    def test_exit_code_one_when_not_reached(self):
        assert main_mod._catalog_exit_code(4, 5) == 1
        assert main_mod._catalog_exit_code(0, 10) == 1


class TestFinalizeCatalogRun:
    """_finalize_catalog_run：总结落盘（FR-021）+ 退出码判定（G1）。"""

    def test_summary_written_and_exit_zero_when_reached(self, tmp_path):
        self._seed_valid(tmp_path, 3)
        catalog_path = tmp_path / "output" / "trex_attack_catalog_x.md"
        exit_code = main_mod._finalize_catalog_run(
            catalog_path, tmp_path, 3, "# 目录摘要\n",
        )
        assert exit_code == 0
        assert catalog_path.read_text(encoding="utf-8") == "# 目录摘要\n"

    def test_summary_still_written_when_not_reached(self, tmp_path):
        self._seed_valid(tmp_path, 2)
        catalog_path = tmp_path / "output" / "trex_attack_catalog_x.md"
        exit_code = main_mod._finalize_catalog_run(
            catalog_path, tmp_path, 5, "# 未达标也落盘\n",
        )
        assert exit_code == 1  # 未达标 → 退出码 1
        assert catalog_path.exists()  # 总结仍落盘（FR-021）
        assert catalog_path.read_text(encoding="utf-8") == "# 未达标也落盘\n"

    def test_empty_content_writes_no_summary_but_still_exit_code(self, tmp_path):
        catalog_path = tmp_path / "output" / "trex_attack_catalog_x.md"
        exit_code = main_mod._finalize_catalog_run(catalog_path, tmp_path, 1, "")
        assert exit_code == 1  # 空摘要时脚本必然为 0，未达标
        assert not catalog_path.exists()

    @staticmethod
    def _seed_valid(tmp_path: Path, n: int) -> None:
        for i in range(n):
            (tmp_path / f"cat_{i}.py").write_text(VALID_CODE, encoding="utf-8")


# ── G2：--clean-scripts 仅删 cat_*.py ────────────────────────────────

class TestCleanCatalogScripts:
    def test_removes_only_cat_scripts(self, tmp_path):
        (tmp_path / "cat_a.py").write_text(VALID_CODE, encoding="utf-8")
        (tmp_path / "cat_b.py").write_text(BROKEN_CODE, encoding="utf-8")
        (tmp_path / "keep.py").write_text(VALID_CODE, encoding="utf-8")
        (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "cat_nested.py").write_text(VALID_CODE, encoding="utf-8")

        removed = main_mod._clean_catalog_scripts(tmp_path)

        assert removed == 2
        assert not (tmp_path / "cat_a.py").exists()
        assert not (tmp_path / "cat_b.py").exists()
        assert (tmp_path / "keep.py").exists()      # 非 cat_ 文件绝不动
        assert (tmp_path / "keep.txt").exists()
        assert (sub / "cat_nested.py").exists()      # 不递归子目录

    def test_missing_dir_removes_zero(self, tmp_path):
        assert main_mod._clean_catalog_scripts(tmp_path / "nope") == 0

    def test_clean_scripts_flag_parsed(self):
        args = _parse(["--trex-explore", "--clean-scripts"])
        assert args.clean_scripts is True
        args2 = _parse(["--trex-explore"])
        assert args2.clean_scripts is False
