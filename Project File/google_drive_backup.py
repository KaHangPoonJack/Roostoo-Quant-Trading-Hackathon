"""
google_drive_backup.py
======================
Backup trading database to Google Drive daily
FREE - Uses 15GB free tier (plenty for trading data)
"""

import os
import datetime
from pathlib import Path

# Google Drive API setup instructions:
# 1. Go to https://console.cloud.google.com/
# 2. Create new project or select existing
# 3. Enable "Google Drive API"
# 4. Create credentials (Service Account)
# 5. Download JSON key file
# 6. Share your Google Drive folder with the service account email

class GoogleDriveBackup:
    def __init__(self, credentials_file='google_credentials.json', folder_id=None):
        """
        Initialize Google Drive backup
        
        Args:
            credentials_file: Path to Google service account JSON key
            folder_id: Google Drive folder ID to store backups (optional)
        """
        self.credentials_file = credentials_file
        self.folder_id = folder_id
        self.service = None
        
    def authenticate(self):
        """Authenticate with Google Drive API"""
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            
            SCOPES = ['https://www.googleapis.com/auth/drive.file']
            
            creds = service_account.Credentials.from_service_account_file(
                self.credentials_file, 
                scopes=SCOPES
            )
            
            self.service = build('drive', 'v3', credentials=creds)
            print("✅ Google Drive authenticated")
            return True
            
        except Exception as e:
            print(f"❌ Google Drive auth failed: {e}")
            print("\n📝 Setup Instructions:")
            print("1. Go to https://console.cloud.google.com/")
            print("2. Create project → Enable Google Drive API")
            print("3. Create Service Account → Download JSON key")
            print("4. Save as 'google_credentials.json' in Project File folder")
            print("5. Share your Drive folder with the service account email")
            return False
    
    def backup_file(self, file_path, description=None):
        """
        Backup a file to Google Drive
        
        Args:
            file_path: Path to file to backup
            description: Optional description for the file
        """
        if not self.service:
            if not self.authenticate():
                return False
        
        try:
            file_name = os.path.basename(file_path)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name_with_date = f"{Path(file_path).stem}_{timestamp}{Path(file_path).suffix}"
            
            # File metadata
            file_metadata = {
                'name': file_name_with_date,
                'description': description or f'Trading bot backup - {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}'
            }
            
            if self.folder_id:
                file_metadata['parents'] = [self.folder_id]
            
            # Upload file
            media = MediaFileUpload(file_path, resumable=True)
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
            
            print(f"✅ Backup uploaded: {file.get('name')}")
            print(f"   Link: {file.get('webViewLink')}")
            return True
            
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return False
    
    def backup_database(self, db_path='trading_data.db'):
        """Backup trading database"""
        if not os.path.exists(db_path):
            print(f"❌ Database not found: {db_path}")
            return False
        
        description = f"Trading DB Backup - {datetime.datetime.now().strftime('%Y-%m-%d')}"
        return self.backup_file(db_path, description)
    
    def cleanup_old_backups(self, keep_days=30):
        """Delete backups older than keep_days"""
        if not self.service:
            return
        
        try:
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=keep_days)
            
            # Query for old backup files
            query = "name contains 'trading_data' and trashed=false"
            results = self.service.files().list(q=query, fields="files(id, name, createdTime)").execute()
            
            files = results.get('files', [])
            
            for file in files:
                created = datetime.datetime.fromisoformat(file['createdTime'].replace('Z', '+00:00'))
                if created < cutoff_date:
                    self.service.files().delete(fileId=file['id']).execute()
                    print(f"🗑️  Deleted old backup: {file['name']}")
            
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")


# ================= USAGE EXAMPLES =================

if __name__ == "__main__":
    # Initialize backup
    drive = GoogleDriveBackup(
        credentials_file='google_credentials.json',
        folder_id='YOUR_DRIVE_FOLDER_ID'  # Optional
    )
    
    # Backup database
    drive.backup_database('trading_data.db')
    
    # Cleanup old backups (keep last 30 days)
    drive.cleanup_old_backups(keep_days=30)
