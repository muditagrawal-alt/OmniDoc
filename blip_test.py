from transformers import BlipProcessor, BlipForConditionalGeneration
from PIL import Image

processor = BlipProcessor.from_pretrained("Salesforce/blip2-t5-small")
model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip2-t5-small")

img = Image.open("test_image.png")

inputs = processor(images=img, text="Describe this image.", return_tensors="pt")
out = model.generate(**inputs)
caption = processor.decode(out[0], skip_special_tokens=True)

print("Caption:", caption)