import os
import firebase_admin
from firebase_admin import credentials, firestore


def initialize_firebase():
    cur_dir = os.path.dirname(__file__)
    parent_dir = os.path.abspath(os.path.join(cur_dir, os.pardir))
    key_path = os.path.join(
        parent_dir, "config", "fantasy-warped-firebase-adminsdk-fbsvc-1fd9535117.json"
    )
    cred = credentials.Certificate(key_path)
    # Initialize Firebase app (Only do this once)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def get_document(db, collection, document_id):
    doc_ref = db.collection(collection).document(document_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None
