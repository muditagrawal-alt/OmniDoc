"""Enhanced image extraction and semantic retrieval."""
import fitz
from PIL import Image
import io
import hashlib
import ollama
import numpy as np
from pathlib import Path
import pickle

MODEL_NAME = "Salesforce/blip-image-captioning-base"
CACHE_DIR = Path(".cache/image_embeddings")
CACHE_DIR.mkdir(exist_ok=True, parents=True)

try:
    from transformers import BlipProcessor, BlipForConditionalGeneration
    processor = BlipProcessor.from_pretrained(MODEL_NAME)
    model = BlipForConditionalGeneration.from_pretrained(MODEL_NAME)
    BLIP_AVAILABLE = True
except Exception as e:
    print(f"⚠️ BLIP model not available: {e}")
    BLIP_AVAILABLE = False

EMBED_MODEL = "nomic-embed-text"


def image_hash(pil_image: Image.Image) -> str:
    """Generate hash of image for deduplication."""
    return hashlib.md5(pil_image.tobytes()).hexdigest()


def caption_image(image: Image.Image) -> str:
    """Generate caption for image using BLIP."""
    if not BLIP_AVAILABLE:
        return "Image (BLIP model not available)"
    
    try:
        inputs = processor(images=image, text="Describe this image.", return_tensors="pt")
        out = model.generate(**inputs, max_new_tokens=50)
        return processor.decode(out[0], skip_special_tokens=True)
    except Exception as e:
        print(f"⚠️ Caption generation failed: {e}")
        return "Image (could not generate caption)"


def embed_image_caption(caption: str) -> list:
    """Get embedding for image caption."""
    try:
        response = ollama.embeddings(
            model=EMBED_MODEL,
            prompt=caption
        )
        return response.get("embedding", [])
    except Exception as e:
        print(f"⚠️ Caption embedding failed: {e}")
        return []


def find_relevant_images_semantic(query: str, images: list, top_k: int = 3) -> list:
    """
    Find relevant images using semantic similarity.
    Returns images with relevance scores.
    """
    if not images:
        return []
    
    try:
        # Embed the query
        response = ollama.embeddings(
            model=EMBED_MODEL,
            prompt=query
        )
        query_emb = response.get("embedding", [])
        
        if not query_emb:
            return []
        
        # Score images
        scored_images = []
        for img in images:
            if img.get("caption_embedding"):
                # Cosine similarity
                query_arr = np.array(query_emb)
                img_arr = np.array(img["caption_embedding"])
                
                norm_q = np.linalg.norm(query_arr)
                norm_i = np.linalg.norm(img_arr)
                
                if norm_q > 0 and norm_i > 0:
                    similarity = np.dot(query_arr, img_arr) / (norm_q * norm_i)
                    if similarity > 0.3:  # Only return if somewhat relevant
                        scored_images.append((similarity, img))
        
        scored_images.sort(reverse=True, key=lambda x: x[0])
        return [img for _, img in scored_images[:top_k]]
    
    except Exception as e:
        print(f"⚠️ Semantic image search failed: {e}")
        return []


def extract_images_with_captions(pdf_path: str, use_cache: bool = True) -> tuple:
    """
    Extract images from PDF with captions and embeddings.
    
    Returns:
    - image_context_text (str) → for RAG
    - images (list of dict) → for UI with semantic info
    """
    doc = fitz.open(pdf_path)
    image_context = []
    images = []
    seen_hashes = set()
    
    for page_num, page in enumerate(doc):
        for img in page.get_images(full=True):
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                
                # Deduplication
                img_hash = image_hash(pil_image)
                if img_hash in seen_hashes:
                    continue
                seen_hashes.add(img_hash)
                
                # Caption generation
                caption = caption_image(pil_image)
                
                # Embedding for semantic search
                caption_embedding = embed_image_caption(caption)
                
                # RAG context
                image_context.append(
                    f"[FIGURE page {page_num + 1}]: {caption}"
                )
                
                # UI data with embeddings
                images.append({
                    "page": page_num + 1,
                    "image": pil_image,
                    "caption": caption,
                    "search_text": caption.lower(),
                    "caption_embedding": caption_embedding,
                    "hash": img_hash
                })
            
            except Exception as e:
                print(f"⚠️ Failed to process image on page {page_num + 1}: {e}")
                continue
    
    return "\n".join(image_context), images


def extract_images_from_docx(docx_path: str) -> tuple:
    """
    Extract images from DOCX file.
    
    Returns:
    - image_context_text (str)
    - images (list of dict)
    """
    try:
        from docx import Document
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
    except ImportError:
        print("⚠️ python-docx not available")
        return "", []
    
    try:
        doc = Document(docx_path)
        image_context = []
        images = []
        seen_hashes = set()
        image_count = 0
        
        # Extract images from document relationships
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    image_part = rel.target_part
                    image_bytes = image_part.blob
                    
                    pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                    
                    # Dedup
                    img_hash = image_hash(pil_image)
                    if img_hash in seen_hashes:
                        continue
                    seen_hashes.add(img_hash)
                    
                    image_count += 1
                    caption = caption_image(pil_image)
                    caption_embedding = embed_image_caption(caption)
                    
                    image_context.append(f"[FIGURE {image_count}]: {caption}")
                    
                    images.append({
                        "page": image_count,
                        "image": pil_image,
                        "caption": caption,
                        "search_text": caption.lower(),
                        "caption_embedding": caption_embedding,
                        "hash": img_hash
                    })
                
                except Exception as e:
                    print(f"⚠️ Failed to extract DOCX image: {e}")
                    continue
        
        return "\n".join(image_context), images
    
    except Exception as e:
        print(f"⚠️ DOCX image extraction failed: {e}")
        return "", []
