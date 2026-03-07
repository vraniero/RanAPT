from pathlib import Path
from dataclasses import dataclass

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".docx": "docx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}


@dataclass
class ScannedFile:
    name: str
    path: Path
    file_type: str
    size: int


def scan_folder(folder_path: str) -> list[ScannedFile]:
    """Recursively scan folder and return supported files."""
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"Folder not found: {folder_path}")

    results: list[ScannedFile] = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        results.append(
            ScannedFile(
                name=f.name,
                path=f,
                file_type=SUPPORTED_EXTENSIONS[ext],
                size=f.stat().st_size,
            )
        )
    return results
