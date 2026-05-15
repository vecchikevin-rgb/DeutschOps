# list_tabs.py
from doc_writer import get_service, DOC_ID
from googleapiclient.discovery import build

service = get_service()
doc = service.documents().get(
    documentId=DOC_ID,
    includeTabsContent=False  # solo metadati, non contenuto
).execute()

tabs = doc.get("tabs", [])
print(f"\nTotale tab: {len(tabs)}\n")
for i, tab in enumerate(tabs):
    props = tab.get("tabProperties", {})
    print(f"  #{i+1:02d} | ID: {props.get('tabId','?'):<20} | "
          f"Index: {props.get('index','?'):>3} | "
          f"Nome: {props.get('title','(senza nome)')}")