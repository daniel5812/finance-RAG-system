from pinecone import Pinecone, ServerlessSpec
import os
from dotenv import load_dotenv

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

index_name = "rag-384"

if not pc.has_index(index_name):
    pc.create_index(
        name=index_name,
        vector_type="dense",
        dimension=384,  # ← חשוב! תואם ל-MiniLM
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"  # תבחר region קרוב אליך
        ),
        deletion_protection="disabled",
        tags={
            "environment": "development"
        }
    )

print("Index ready!")
