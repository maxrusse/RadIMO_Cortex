#!/usr/bin/env python3
"""
Code Aggregator - Documentation Export Tool

Aggregates project files into separate text outputs for documentation review,
AI input, or archival purposes.

USAGE:
    python code_aggregator.py                    # Run in current directory
    python code_aggregator.py -p /path/to/proj   # Run in specific directory

OUTPUT FILES:
    1. markdown_export.txt - All markdown documentation (.md)
    2. code_web_export.txt - Code and web files (.py, .html, .js, .css, .ipynb, .ico)
    3. config_export.txt - Configuration files (.yaml, .json, .toml, .ini, .csv, .txt)
    4. aggregation_summary.txt - Summary report with file counts

CUSTOMIZATION:
    Edit EXCLUDE_DIRS to exclude additional directories
    Edit *_EXTENSIONS sets to add more file types

FEATURES:
    - Automatic file categorization
    - Excludes .git, node_modules, __pycache__, etc.
    - UTF-8 encoding support with error handling
    - Sorted file listing for consistency
    - Detailed table of contents with file sizes
    - Timestamp tracking
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set

# File type categories
MARKDOWN_EXTENSIONS = {'.md', '.markdown'}
CODE_WEB_EXTENSIONS = {'.py', '.html', '.htm', '.js', '.css', '.ipynb', '.ico'}
CONFIG_EXTENSIONS = {'.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.conf', '.txt', '.csv'}

# Directories to exclude
EXCLUDE_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    'env', '.pytest_cache', '.mypy_cache', 'dist', 'build',
    '.idea', '.vscode', 'uploads', 'output'
}

# Files to exclude
EXCLUDE_FILES = {
    '.gitignore', '.DS_Store', 'requirements.txt',
    'markdown_export.txt', 'code_web_export.txt', 'config_export.txt', 'aggregation_summary.txt'
}


class CodeAggregator:
    """Aggregates project files into categorized text outputs"""

    def __init__(self, root_path: str = '.'):
        self.root_path = Path(root_path).resolve()
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded"""
        parts = path.parts
        for part in parts:
            if part in EXCLUDE_DIRS:
                return True
        if path.name in EXCLUDE_FILES:
            return True
        return False

    def collect_files(self) -> Dict[str, List[Path]]:
        """Collect all files categorized by type"""
        files = {
            'markdown': [],
            'code_web': [],
            'config': []
        }

        for file_path in self.root_path.rglob('*'):
            if not file_path.is_file():
                continue

            if self.should_exclude(file_path):
                continue

            suffix = file_path.suffix.lower()

            if suffix in MARKDOWN_EXTENSIONS:
                files['markdown'].append(file_path)
            elif suffix in CODE_WEB_EXTENSIONS:
                files['code_web'].append(file_path)
            elif suffix in CONFIG_EXTENSIONS:
                files['config'].append(file_path)

        # Sort files by path for consistent output
        for category in files:
            files[category].sort()

        return files

    def format_file_content(self, file_path: Path, category: str) -> str:
        """Format a single file's content with headers"""
        relative_path = file_path.relative_to(self.root_path)
        separator = "=" * 80

        output = f"\n{separator}\n"
        output += f"FILE: {relative_path}\n"
        output += f"SIZE: {file_path.stat().st_size} bytes\n"
        output += f"{separator}\n\n"

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                output += content
                if not content.endswith('\n'):
                    output += '\n'
        except Exception as e:
            output += f"[ERROR reading file: {e}]\n"

        output += f"\n{separator}\n"
        output += f"END OF FILE: {relative_path}\n"
        output += f"{separator}\n\n"

        return output

    def create_export_file(self, category: str, files: List[Path], output_filename: str):
        """Create an export file for a category"""
        if not files:
            print(f"  No files found for category: {category}")
            return

        output_path = self.root_path / output_filename

        with open(output_path, 'w', encoding='utf-8') as out:
            # Write header
            header = f"""
{'#' * 80}
# {category.upper().replace('_', ' ')} FILES EXPORT
# Generated: {self.timestamp}
# Project: {self.root_path.name}
# Total files: {len(files)}
{'#' * 80}

TABLE OF CONTENTS:
"""
            out.write(header)

            # Write table of contents
            for i, file_path in enumerate(files, 1):
                relative_path = file_path.relative_to(self.root_path)
                out.write(f"{i:3d}. {relative_path}\n")

            out.write(f"\n{'#' * 80}\n")
            out.write("# FILE CONTENTS\n")
            out.write(f"{'#' * 80}\n\n")

            # Write each file's content
            for file_path in files:
                content = self.format_file_content(file_path, category)
                out.write(content)

        print(f"  ✓ Created: {output_filename} ({len(files)} files)")

    def generate_summary(self, files: Dict[str, List[Path]]) -> str:
        """Generate a summary of the aggregation"""
        summary = f"""
{'#' * 80}
# CODE AGGREGATION SUMMARY
# Generated: {self.timestamp}
# Project: {self.root_path.name}
{'#' * 80}

FILE COUNTS BY CATEGORY:
  - Markdown files: {len(files['markdown'])}
  - Code/Web files: {len(files['code_web'])}
  - Config files: {len(files['config'])}
  - Total files: {sum(len(f) for f in files.values())}

OUTPUT FILES CREATED:
  - markdown_export.txt - Documentation files
  - code_web_export.txt - Python and HTML files
  - config_export.txt - Configuration files

{'#' * 80}
"""
        return summary

    def run(self):
        """Run the aggregation process"""
        print(f"\n{'=' * 80}")
        print(f"CODE AGGREGATOR")
        print(f"Project: {self.root_path.name}")
        print(f"Path: {self.root_path}")
        print(f"{'=' * 80}\n")

        print("Collecting files...")
        files = self.collect_files()

        print(f"\nFound:")
        print(f"  - {len(files['markdown'])} markdown files")
        print(f"  - {len(files['code_web'])} code/web files")
        print(f"  - {len(files['config'])} config files")

        print("\nGenerating exports...")
        self.create_export_file('markdown', files['markdown'], 'markdown_export.txt')
        self.create_export_file('code_web', files['code_web'], 'code_web_export.txt')
        self.create_export_file('config', files['config'], 'config_export.txt')

        # Print summary
        summary = self.generate_summary(files)
        print(summary)

        # Save summary to file
        summary_path = self.root_path / 'aggregation_summary.txt'
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        print(f"Summary saved to: aggregation_summary.txt")

        print(f"\n{'=' * 80}")
        print("✓ Aggregation complete!")
        print(f"{'=' * 80}\n")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Aggregate project files into categorized text exports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python code_aggregator.py                    # Run in current directory
  python code_aggregator.py -p /path/to/proj   # Run in specific directory
        """
    )
    parser.add_argument(
        '-p', '--path',
        default='.',
        help='Root path of the project (default: current directory)'
    )

    args = parser.parse_args()

    aggregator = CodeAggregator(args.path)
    aggregator.run()


if __name__ == '__main__':
    main()
