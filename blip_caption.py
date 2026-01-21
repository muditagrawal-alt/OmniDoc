# blip_caption.py
import os
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration

# Choose a smaller BLIP model for local usage
MODEL_NAME = "Salesforce/blip-image-captioning-base"

# Load processor and model once
print("Loading BLIP model...")
processor = BlipProcessor.from_pretrained(MODEL_NAME)
model = BlipForConditionalGeneration.from_pretrained(MODEL_NAME)
print("BLIP model loaded.")

def generate_captions(image_folder: str):
    """
    Generates captions for all images in a folder.

    Args:
        image_folder (str): path to folder containing images

    Returns:
        List of dicts: [{'page': int, 'path': str, 'caption': str}]
    """
    if not os.path.exists(image_folder):
        raise FileNotFoundError(f"Folder not found: {image_folder}")

    captions = []

    for filename in sorted(os.listdir(image_folder)):
        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            path = os.path.join(image_folder, filename)
            # Extract page number from filename if available
            page_str = filename.split("_")[1] if "page_" in filename else "unknown"
            try:
                page = int(page_str)
            except ValueError:
                page = -1

            # Load image
            img = Image.open(path).convert("RGB")

            # Generate caption
            inputs = processor(images=img, text="Describe this image.", return_tensors="pt")
            out = model.generate(**inputs)
            caption = processor.decode(out[0], skip_special_tokens=True)

            captions.append({
                "page": page,
                "path": path,
                "caption": caption
            })

    return captions

if __name__ == "__main__":
    folder = input("Enter folder containing images: ").strip()
    results = generate_captions(folder)

    print(f"\nGenerated captions for {len(results)} images:\n")
    for r in results:
        print(f"Page {r['page']} → {r['path']}")
        print(f"Caption: {r['caption']}\n")