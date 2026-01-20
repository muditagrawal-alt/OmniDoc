import fitz  # PyMuPDF
import os

def extract_images_from_pdf(
    pdf_path: str,
    output_dir: str = "extracted_images"
):
    """
    Extracts all images/diagrams from a PDF.

    Returns:
        List of dicts with keys: page, path
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    os.makedirs(output_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    extracted = []

    for page_index, page in enumerate(doc):
        images = page.get_images(full=True)

        for img_index, img in enumerate(images):
            xref = img[0]
            base_image = doc.extract_image(xref)

            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            image_name = f"page_{page_index}_img_{img_index}.{image_ext}"
            image_path = os.path.join(output_dir, image_name)

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            extracted.append({
                "page": page_index,
                "path": image_path
            })

    return extracted

if __name__ == "__main__":
    pdf_path = input("Enter PDF path: ").strip()

    images = extract_images_from_pdf(pdf_path)

    print(f"\nExtracted {len(images)} images:\n")
    for img in images:
        print(f"Page {img['page']} → {img['path']}")