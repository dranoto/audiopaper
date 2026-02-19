import os
import requests

# Ragflow API Client
class RagflowClient:
    def __init__(self, url, api_key):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
    
    def request(self, method, path, **kwargs):
        url = f"{self.url}/api/v1{path}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    
    def list_datasets(self):
        result = self.request('GET', '/datasets')
        return result.get('data', [])
    
    def list_documents(self, dataset_id, page=1, size=50):
        result = self.request('GET', f'/datasets/{dataset_id}/documents?page={page}&size={size}')
        return result.get('data', {}).get('docs', []), result.get('data', {}).get('total', 0)
    
    def get_document_chunks(self, dataset_id, document_id, page=1, size=100):
        """Get all chunks from a document for importing"""
        result = self.request('GET', f'/datasets/{dataset_id}/documents/{document_id}/chunks?page={page}&size={size}')
        chunks = result.get('data', {}).get('chunks', [])
        
        # Handle pagination
        total = result.get('data', {}).get('total', 0)
        if page * size < total:
            more_chunks, _ = self.get_document_chunks(dataset_id, document_id, page + 1, size)
            chunks.extend(more_chunks)
        
        return chunks
    
    def get_document_content(self, dataset_id, document_id):
        """Get full text content from a document by combining chunks"""
        chunks = self.get_document_chunks(dataset_id, document_id)
        
        # Sort by chunk index if available
        chunks.sort(key=lambda x: x.get('chunk_order', 0))
        
        # Combine all chunk content
        content_parts = []
        for chunk in chunks:
            content = chunk.get('content', '')
            if content:
                content_parts.append(content)
        
        return '\n\n'.join(content_parts)


def get_ragflow_client(settings):
    """Create Ragflow client from settings"""
    url = settings.ragflow_url or os.environ.get('RAGFLOW_URL')
    api_key = settings.ragflow_api_key or os.environ.get('RAGFLOW_API_KEY')
    
    if not url or not api_key:
        return None
    
    return RagflowClient(url, api_key)
