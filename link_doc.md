To link a Document ID (document_id / file_id) to Azure Blob Storage throughout the entire lifecycle (ingestion ➔ downloading ➔ processing ➔ storing results ➔ downstream access), enterprise IDP systems use a deterministic storage hierarchy + metadata linking.
Here is the complete architecture, storage path rules, and exact implementation logic.
1. The Azure Storage Path Convention
Instead of storing files randomly in a flat container, use a deterministic virtual directory hierarchy based on {document_id}:
Plain Text
textContainer: idp-documents (or your configured container)│└── documents/    └── {document_id}/                               <-- Root for this document run        ├── source/        │   └── {file_name}                          <-- Original uploaded document        ├── results/        │   └── result.json                          <-- Final extracted JSON        └── grouped_pdfs/                            <-- Split sub-documents (BOP Dec, Schedules)            ├── group_001_pages_1-2_BOP_DEC_PAGE.pdf            └── group_002_pages_3-6_LOCATION_SCHEDULE.pdf


Why this structure is best:
Convention over Configuration: Any system that has {document_id} can immediately construct the exact blob path without querying a database:
Source: documents/{document_id}/source/{file_name}
Results: documents/{document_id}/results/result.json
Split PDFs: documents/{document_id}/grouped_pdfs/{subdoc_name}
Atomic Cleanliness & Isolation: All artifacts for a single document run live under one prefix (documents/{document_id}/). Deleting or archiving a document is as simple as deleting that prefix.
2. The Complete End-to-End Flow
Plain Text
mermaidsequenceDiagram    autonumber    actor User as Client / Upstream    participant API as FastAPI (app/main.py)    participant Blob as Azure Blob Storage    participant Engine as Andromeda Processor    participant Downstream as Downstream (Guidewire / UI)    User->>API: Upload Document (or send Blob URL)    API->>API: Generate document_id (UUID)    API->>Blob: Upload source: documents/{document_id}/source/{file_name}    API->>Engine: Start process(document_id, local_temp_file)    Engine->>Engine: OCR -> Group -> Extract -> Deconflict -> Evidence Score    Engine->>Blob: Upload results: documents/{document_id}/results/result.json    Engine->>Blob: Upload split PDFs: documents/{document_id}/grouped_pdfs/*.pdf    Downstream->>API: Query by document_id    API-->>Downstream: Return result.json + SAS download URLs for source & split PDFs


3. How to Link document_id to Storage in Code
We already have app/helpers/azure_storage.py. Here is how to wire the linking logic:
Step A: Standardize the Path Resolver
In azure_storage.py, define the deterministic path builder:
Plain Text
pythonclass DocumentStoragePaths:    @staticmethod    def source_blob_path(document_id: str, file_name: str) -> str:        return f"documents/{document_id}/source/{file_name}"    @staticmethod    def result_blob_path(document_id: str) -> str:        return f"documents/{document_id}/results/result.json"    @staticmethod    def split_pdf_path(document_id: str, split_pdf_name: str) -> str:        return f"documents/{document_id}/grouped_pdfs/{split_pdf_name}"


Step B: Tag Azure Blob with Metadata
When uploading to Azure Blob Storage, attach the document_id into the blob's metadata headers so you can search/filter blobs directly in Azure:
Plain Text
pythondef upload_source_document(file_path: str, document_id: str, file_name: str) -> str:    blob_path = DocumentStoragePaths.source_blob_path(document_id, file_name)        settings = AzureStorageSettings()    service_client = get_blob_service_client(settings)    container_client = service_client.get_container_client(settings.default_container)    blob_client = container_client.get_blob_client(blob_path)    # Attach document_id as Azure Blob metadata    metadata = {        "document_id": document_id,        "original_filename": file_name,        "status": "received"    }    with open(file_path, "rb") as f:        blob_client.upload_blob(f, overwrite=True, metadata=metadata)    return blob_client.url


Step C: In step_save_results (andromeda_processor.py)
When step_save_results finishes, persist the results directly to Azure Blob and embed the storage paths in result.json:
Plain Text
python    # Inside step_save_results(s: dict):    document_id = s.get("file_id")    file_name = s.get("file_name")    # If Azure storage configured, upload result and split PDFs    azure_storage_info = {}    if os.getenv("AZURE_STORAGE_ACCOUNT_URL") or os.getenv("AZURE_STORAGE_CONNECTION_STRING"):        try:            from app.helpers.azure_storage import (                upload_file_to_blob,                 DocumentStoragePaths            )                        # 1. Upload result.json            result_blob = DocumentStoragePaths.result_blob_path(document_id)            result_url = upload_file_to_blob(                file_path=result_path,                blob_name=result_blob            )                        # 2. Upload split PDFs            split_urls = []            for g_name in group_pdf_paths:                local_g_path = f"{BASE_PATH}/results/{document_id}/grouped_pdfs/{g_name}"                if os.path.exists(local_g_path):                    split_blob = DocumentStoragePaths.split_pdf_path(document_id, g_name)                    split_url = upload_file_to_blob(local_g_path, blob_name=split_blob)                    split_urls.append(split_url)            azure_storage_info = {                "container": os.getenv("AZURE_STORAGE_CONTAINER_NAME", "idp-documents"),                "source_blob": DocumentStoragePaths.source_blob_path(document_id, file_name),                "result_blob": result_blob,                "result_url": result_url,                "split_pdf_urls": split_urls            }        except Exception as e:            print(f"[LOG] Azure blob upload failed: {e}")    # Add storage info into the final payload    result_payload["storage"] = azure_storage_info


4. What Downstream Receives in result.json
Downstream gets the extracted data and the direct links to the storage paths:
Plain Text
json{  "document_id": "a5d892bc-7a14-411a-b362-e64e9e0486fa",  "document_type": "BOP_DEC_PAGE",  "storage": {    "container": "idp-documents",    "source_blob": "documents/a5d892bc-7a14-411a-b362-e64e9e0486fa/source/claim_form.pdf",    "result_blob": "documents/a5d892bc-7a14-411a-b362-e64e9e0486fa/results/result.json",    "result_url": "https://mystorage.blob.core.windows.net/idp-documents/documents/a5d892bc.../results/result.json"  },  "deconflicted_fields": {    "named_insured": { "value": "SUNNYVALE CONDOMINIUM", "confidence": 0.95 },    "insurance_carrier": { "value": "Liberty Mutual", "confidence": 0.92 }  }}


5. Downloading via SAS URL for Secure Downstream Access
Downstream or frontend applications should never need storage account keys to view documents. When downstream requests a document by document_id, the API generates a short-lived SAS (Shared Access Signature) token (e.g., valid for 30 minutes):
Plain Text
python@app.get("/files/{document_id}/download_url")async def get_document_download_url(document_id: str):    """Returns a secure, temporary 30-minute SAS URL for the original document."""    file_info = _build_file_info(document_id)    file_name = file_info.get("original_filename")        blob_path = DocumentStoragePaths.source_blob_path(document_id, file_name)    sas_url = generate_blob_sas_url(blob_path, expiry_minutes=30)        return {"document_id": document_id, "download_url": sas_url}
This guarantees that:
Every document run has a clean, isolated Azure Blob path keyed by document_id.
The storage path is 100% predictable.
Downstream systems and underwriters can download or preview source documents securely without sharing storage credentials.