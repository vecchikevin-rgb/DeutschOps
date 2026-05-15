# test_backup.py
from doc_writer import get_service, backup_doc

service = get_service()
path = backup_doc(service, label="test")
print(f"Backup OK: {path}")