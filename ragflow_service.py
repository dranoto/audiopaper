import os
import requests

# Ragflow API Client
class RagflowClient:
    def __init__(self, url, api_key, allowed_datasets=None):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.allowed_datasets = allowed_datasets or []
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
        all_datasets = result.get('data', [])
        
        # Filter by allowed datasets if specified
        if self.allowed_datasets:
            return [d for d in all_datasets if d.get('name') in self.allowed_datasets]
        return all_datasets
    
    def list_documents(self, dataset_id, page=1, size=50):
        result = self.request('GET', f'/datasets/{dataset_id}/documents?page={page}&size={size}')
        docs = result.get('data', {}).get('docs', [])
        
        # Enrich with PubMed titles for PMC files
        docs = self._enrich_with_pubmed_titles(docs)
        
        return docs, result.get('data', {}).get('total', 0)
    
    def _enrich_with_pubmed_titles(self, docs):
        """Fetch human-readable titles and publication dates from PubMed for PMC files"""
        # Extract PMIDs from file names like "PMC12527568.md"
        pmids = []
        for doc in docs:
            name = doc.get('name', '')
            if name.startswith('PMC') and name.endswith('.md'):
                pmid = name[3:-3]  # Remove 'PMC' prefix and '.md' suffix
                pmids.append((doc.get('id'), pmid))
        
        if not pmids:
            return docs
        
        # Batch fetch from PubMed (can handle multiple IDs)
        pmid_list = [p[1] for p in pmids]
        try:
            # PubMed ESummary can handle multiple IDs
            pmid_str = ','.join(pmid_list)
            resp = requests.get(
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={'db': 'pubmed', 'id': pmid_str, 'retmode': 'json'},
                timeout=10
            )
            data = resp.json()
            
            # Map PMID to title and pubdate
           _map = {}
            info for pmid in pmid_list:
                try:
                    result = data.get('result', {}).get(pmid, {})
                    title = result.get('title', '')
                    pubdate = result.get('pubdate', '')
                    if title:
                        # Truncate long titles
                        if len(title) > 80:
                            title = title[:77] + '...'
                        info_map[pmid] = {'title': title, 'pubdate': pubdate}
                except:
                    pass
            
            # Update docs with titles and dates
            for doc in docs:
                name = doc.get('name', '')
                if name.startswith('PMC') and name.endswith('.md'):
                    pmid = name[3:-3]
                    if pmid in info_map:
                        doc['title'] = info_map[pmid]['title']
                        doc['pubdate'] = info_map[pmid]['pubdate']
                    else:
                        doc['title'] = name
                        doc['pubdate'] = ''
                else:
                    doc['title'] = doc.get('name', '')
                    doc['pubdate'] = ''
                    
        except Exception as e:
            # If PubMed lookup fails, just use filename
            for doc in docs:
                doc['title'] = doc.get('name', '')
                doc['pubdate'] = ''
        
        return docs
    
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
    allowed_datasets_str = os.environ.get('RAGFLOW_ALLOWED_DATASETS', '')
    allowed_datasets = [d.strip() for d in allowed_datasets_str.split(',') if d.strip()]
    
    if not url or not api_key:
        return None
    
    return RagflowClient(url, api_key, allowed_datasets)
