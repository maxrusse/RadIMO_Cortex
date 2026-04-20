import unittest

from lib.utils import build_worker_sort_key, format_worker_display_name


class TestWorkerNameSorting(unittest.TestCase):
    def test_titles_and_codes_are_ignored_in_sort_key(self) -> None:
        key = build_worker_sort_key("Claudia Dr Ehritt-Braun (CEB)")
        self.assertTrue(key.startswith("ehritt-braun|claudia"))

    def test_particles_are_ignored_in_sort_key(self) -> None:
        key = build_worker_sort_key("Gregor Teutul von (GT)")
        self.assertTrue(key.startswith("teutul von|gregor"))

    def test_compound_titles_are_ignored_in_sort_key(self) -> None:
        key = build_worker_sort_key("Maximilian Dr Dipl-Ing Löffler (MDL)")
        self.assertTrue(key.startswith("löffler|maximilian"))

    def test_sorted_names_follow_surname_like_order(self) -> None:
        names = [
            "Gregor Teutul von (GT)",
            "Maximilian Dr Dipl-Ing Löffler (MDL)",
            "Claudia Dr Ehritt-Braun (CEB)",
            "Jan-Felix Seebeck (JS)",
        ]

        sorted_names = sorted(names, key=build_worker_sort_key)

        self.assertEqual(
            sorted_names,
            [
                "Claudia Dr Ehritt-Braun (CEB)",
                "Maximilian Dr Dipl-Ing Löffler (MDL)",
                "Jan-Felix Seebeck (JS)",
                "Gregor Teutul von (GT)",
            ],
        )

    def test_format_worker_display_name_supports_last_first_style(self) -> None:
        formatted = format_worker_display_name("Anna Müller (AM)", "AM", style="last_first_id")
        self.assertEqual(formatted, "Müller, Anna (AM)")

    def test_format_worker_display_name_supports_raw_style(self) -> None:
        formatted = format_worker_display_name("Anna Müller (AM)", "AM", style="raw")
        self.assertEqual(formatted, "Anna Müller (AM)")

    def test_format_worker_display_name_normalizes_nested_worker_id_labels(self) -> None:
        formatted = format_worker_display_name(
            "Sascha Klaus (KLSA)",
            "Sascha Klaus (KLSA)",
            style="last_first_id",
        )
        self.assertEqual(formatted, "Klaus, Sascha (KLSA)")


if __name__ == "__main__":
    unittest.main()
