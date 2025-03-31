import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
import json

load_dotenv()
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


def initialize_firebase():
    # Initialize Firebase app (Only do this once)
    if not firebase_admin._apps:
        google_application_credentials_json = json.loads(GOOGLE_APPLICATION_CREDENTIALS)
        google_application_credentials_json["private_key"] = (
            google_application_credentials_json["private_key"].replace("\\n", "\n")
        )
        cred = credentials.Certificate(google_application_credentials_json)
        firebase_admin.initialize_app(cred)
    return firestore.client()


def get_document(db, collection, document_id):
    doc_ref = db.collection(collection).document(document_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None
