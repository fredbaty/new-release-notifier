import requests
import shutil
import subprocess
import zipfile
from pathlib import Path

import typer
from tqdm import tqdm

app = typer.Typer()

@app.command()
def main(
    download_urls: list[str] = typer.Argument(..., help="One or more download URLs"),
    download_dir: str = typer.Option("~/temp-downloads", "--download-dir", "-d", help="Directory for temporary downloads")
):
    """Download and import Bandcamp purchases using beets."""
    print("=== Bandcamp Downloader ===")

    for download_url in download_urls:
        print(f"Downloading: {download_url}")
        
        # Clear download directory
        temp_dir = Path(download_dir).expanduser()
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        for item in temp_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        
        # Set file path
        file_path = temp_dir / "download_file"

        # Download the file
        try:
            response = requests.get(download_url, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            response.raise_for_status()
            
            with open(file_path, 'wb') as f:
                with tqdm(total=total_size, unit='B', unit_scale=True, desc="Downloading") as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
             
        except requests.RequestException as e:
            print(f"Error: Failed to download the file. Please check the URL and try again.")
            continue
        
        # Extract if zip, otherwise use file directly
        import_path = file_path
        if zipfile.is_zipfile(file_path):
            print("Extracting zip file...")
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            import_path = temp_dir

        # Import the downloaded file using beets
        try:
            subprocess.run(["beet", "import", str(import_path)], check=True)
            print("Album imported successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to import the file. Please check the file and try again.")
            continue

if __name__ == "__main__":
    app()