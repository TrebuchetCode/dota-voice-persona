import os
import json
import requests
import zipfile

def download_file(url, save_path):
    if os.path.exists(save_path):
        return
    print(f"📥 Downloading: {os.path.basename(save_path)}...")
    r = requests.get(url, stream=True)
    with open(save_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            if chunk: f.write(chunk)

def main():
    # 1. Create Structure
    for folder in ["assets", "models", "outputs"]:
        os.makedirs(folder, exist_ok=True)

    # 2. Base Assets (Hubert/RMVPE) - Always needed
    base_assets = {
        "assets/hubert_base.pt": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt",
        "assets/rmvpe.pt": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt"
    }
    print("\n--- Checking Base Engine Assets ---")
   # for path, url in base_assets.items():
    #    download_file(url, path)

    # 3. Interactive Hero Menu
    if not os.path.exists('heroes.json'):
        print("❌ Error: heroes.json not found!")
        return

    with open('heroes.json', 'r') as f:
        data = json.load(f)
        heroes = data['heroes']

    print("\n--- Available Dota Personas ---")
    for i, hero in enumerate(heroes):
        # Check if already installed
        is_installed = os.path.exists(os.path.join("models", hero['id'], f"{hero['id']}.pth"))
        status = "[Installed]" if is_installed else "[Not Downloaded]"
        print(f"{i+1}. {hero['name']} {status}")

    print("\nOptions:")
    print(" - Enter numbers separated by commas (e.g. 1,3)")
    print(" - Type 'all' to download everything")
    print(" - Press Enter to skip/finish")
    
    user_input = input("\nYour choice: ").strip().lower()

    selected = []
    if user_input == 'all':
        selected = heroes
    elif user_input:
        try:
            indices = [int(x.strip()) - 1 for x in user_input.split(',')]
            selected = [heroes[i] for i in indices if 0 <= i < len(heroes)]
        except (ValueError, IndexError):
            print("⚠️ Invalid input. Proceeding with setup...")

    # 4. Download and Rename Selected Heroes
    for hero in selected:
        hero_id = hero['id']
        hero_dir = os.path.join("models", hero_id)
        os.makedirs(hero_dir, exist_ok=True)
        
        pth_target = os.path.join(hero_dir, f"{hero_id}.pth")
        
        if not os.path.exists(pth_target) and "zip_url" in hero:
            zip_tmp = f"{hero_id}_temp.zip"
            download_file(hero['zip_url'], zip_tmp)

            print(f"📦 Extracting {hero['name']}...")
            with zipfile.ZipFile(zip_tmp, 'r') as zip_ref:
                zip_ref.extractall(hero_dir)
            
            # Smart Rename: Find ANY .pth and .index inside and rename to hero_id
            for file in os.listdir(hero_dir):
                source = os.path.join(hero_dir, file)
                if file.endswith(".pth") and file != f"{hero_id}.pth":
                    os.replace(source, pth_target)
                elif file.endswith(".index") and file != f"{hero_id}.index":
                    os.replace(source, os.path.join(hero_dir, f"{hero_id}.index"))
            
            if os.path.exists(zip_tmp): os.remove(zip_tmp)
            print(f"✅ {hero['name']} ready.")

if __name__ == "__main__":
    main()