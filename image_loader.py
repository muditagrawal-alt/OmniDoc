import fitz
from PIL import Image
import io
from transformers import BlipProcessor, BlipForConditionalGeneration

MODEL_NAME = "Salesforce/blip-image-captioning-base"

processor = BlipProcessor.from_pretrained(MODEL_NAME)
model = BlipForConditionalGeneration.from_pretrained(MODEL_NAME)

def caption_image(image: Image.Image) -> str:
    inputs = processor(images=image, text="Describe this image.", return_tensors="pt")
    out = model.generate(**inputs, max_new_tokens=50)
    return processor.decode(out[0], skip_special_tokens=True)

def extract_images_with_captions(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    captions = []

    for page_num, page in enumerate(doc):
        for img in page.get_images(full=True):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            caption = caption_image(image)
            captions.append(f"[FIGURE page {page_num+1}]: {caption}")

    return "\n".join(captions)