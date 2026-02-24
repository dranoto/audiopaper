import os
import requests
import time


# Simple module-level cache for PubMed lookups (24 hour TTL)
_pubmed_cache = {}
_pubmed_cache_ttl = 86400  # 24 hours


# Ragflow API Client
class RagflowClient:
    def __init__(self, url, api_key, allowed_datasets=None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.allowed_datasets = allowed_datasets or []
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )

    def request(self, method, path, **kwargs):
        url = f"{self.url}/api/v1{path}"
        try:
            resp = self.session.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            # Try to get more details from the response
            try:
                error_data = resp.json()
                error_msg = (
                    error_data.get("message") or error_data.get("code") or str(e)
                )
            except:
                error_msg = str(e)
            raise Exception(f"Ragflow API error: {error_msg}") from e
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ragflow connection error: {str(e)}") from e

    def list_datasets(self):
        result = self.request("GET", "/datasets")
        all_datasets = result.get("data", [])

        # Filter by allowed datasets if specified
        if self.allowed_datasets:
            return [d for d in all_datasets if d.get("name") in self.allowed_datasets]
        return all_datasets

    def get_dataset(self, dataset_id):
        """Get a single dataset by ID."""
        result = self.request("GET", f"/datasets/{dataset_id}")
        return result.get("data", {})

    def list_documents(self, dataset_id, page=1, size=100):
        result = self.request(
            "GET", f"/datasets/{dataset_id}/documents?page={page}&size={size}"
        )
        docs = result.get("data", {}).get("docs", [])

        # Enrich with title and pubdate from PubMed for PMC files
        docs = self._enrich_documents(docs)

        # Sort by publication date (newest first)
        docs = self._sort_by_date(docs)

        return docs, result.get("data", {}).get("total", 0)

    def _enrich_documents(self, docs):
        """Extract title from filename and fetch pubdate from PubMed"""
        import re

        # First pass: extract PMC IDs and prepare docs
        pmc_to_doc = {}
        for doc in docs:
            name = doc.get("name", "") or doc.get("location", "")

            # Extract title from filename (before " - PMCxxxxx")
            # Format: "Title Here - PMC12345678.md"
            match = re.match(r"^(.+?)\s*-\s*PMC(\d+)(?:\(\d+\))?\.md$", name)
            if match:
                extracted_title = match.group(1).strip()
                pmc_id = match.group(2)
                pmc_to_doc[pmc_id] = (doc, extracted_title)
                doc["extracted_title"] = extracted_title
                doc["pmc_id"] = pmc_id
            else:
                # No PMC ID - use filename as title
                doc["extracted_title"] = name.replace(".md", "")
                doc["pmc_id"] = None

            # Default to create_date if no pubdate
            doc["pubdate"] = (
                doc.get("create_date", "")[:10] if doc.get("create_date") else ""
            )

        if not pmc_to_doc:
            return docs

        # Look up PubMed for publication dates
        pmc_ids = list(pmc_to_doc.keys())
        pubdate_map = self._fetch_pubmed_dates(pmc_ids)

        # Update docs with PubMed info
        for doc in docs:
            pmc_id = doc.get("pmc_id")
            if pmc_id and pmc_id in pubdate_map:
                pub_info = pubdate_map[pmc_id]
                if pub_info.get("pubdate"):
                    doc["pubdate"] = pub_info["pubdate"]
                if pub_info.get("title"):
                    doc["title"] = pub_info["title"]
            elif pmc_id:
                # Use extracted title if no PubMed title
                doc["title"] = doc.get("extracted_title", "")
            else:
                doc["title"] = doc.get("extracted_title", "")

        return docs

    def _fetch_pubmed_dates(self, pmc_ids):
        """Fetch publication dates from PubMed for PMC IDs with caching"""
        if not pmc_ids:
            return {}

        # Check cache first
        result = {}
        uncached_ids = []
        current_time = time.time()

        for pmc_id in pmc_ids:
            if pmc_id in _pubmed_cache:
                cached_data, cached_time = _pubmed_cache[pmc_id]
                if current_time - cached_time < _pubmed_cache_ttl:
                    result[pmc_id] = cached_data
                else:
                    uncached_ids.append(pmc_id)
            else:
                uncached_ids.append(pmc_id)

        if not uncached_ids:
            return result

        import requests

        pmc_to_pmid = {}

        # Step 1: Convert PMC to PMID
        for pmc_id in uncached_ids:
            try:
                resp = requests.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
                    params={
                        "dbfrom": "pmc",
                        "linkname": "pmc_pubmed",
                        "id": pmc_id,
                        "retmode": "json",
                    },
                    timeout=10,
                )
                data = resp.json()
                links = data.get("linksets", [{}])[0].get("linksetdbs", [{}])
                if links and links[0].get("links"):
                    pmc_to_pmid[pmc_id] = str(links[0]["links"][0])
            except:
                pass

        if not pmc_to_pmid:
            for pmc_id in uncached_ids:
                try:
                    resp = requests.get(
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                        params={
                            "db": "pubmed",
                            "term": f"{pmc_id}[pmcid]",
                            "retmode": "json",
                            "retmax": 1,
                        },
                        timeout=10,
                    )
                    data = resp.json()
                    ids = data.get("esearchresult", {}).get("idlist", [])
                    if ids:
                        pmc_to_pmid[pmc_id] = ids[0]
                except:
                    pass

        if not pmc_to_pmid:
            return result

        # Step 2: Get publication details
        pmid_list = list(pmc_to_pmid.values())
        try:
            pmid_str = ",".join(pmid_list[:30])
            resp = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pubmed", "id": pmid_str, "retmode": "json"},
                timeout=15,
            )
            data = resp.json()

            for pmc_id, pmid in pmc_to_pmid.items():
                try:
                    pubmed_data = data.get("result", {}).get(pmid, {})
                    title = pubmed_data.get("title", "")
                    pubdate = pubmed_data.get("pubdate", "")
                    if pubdate:
                        year = pubdate.split()[0] if pubdate else ""
                        pubdate = year
                    pub_info = {"title": title, "pubdate": pubdate}
                    result[pmc_id] = pub_info
                    _pubmed_cache[pmc_id] = (pub_info, current_time)
                except:
                    pass

            return result
        except:
            return result

    def _sort_by_date(self, docs):
        """Sort documents by publication date, newest first"""

        def get_date(doc):
            pubdate = doc.get("pubdate", "")
            if pubdate and len(pubdate) >= 4:
                try:
                    return int(pubdate[:4])  # Year
                except:
                    pass
            # Fallback to (when create_date uploaded to RagFlow)
            create = doc.get("create_date", "")
            if create and len(create) >= 4:
                try:
                    return int(create[:4])
                except:
                    pass
            return 0

        return sorted(docs, key=get_date, reverse=True)

    def get_document_chunks(self, dataset_id, document_id, page=1, size=100):
        """Get all chunks from a document for importing"""
        result = self.request(
            "GET",
            f"/datasets/{dataset_id}/documents/{document_id}/chunks?page={page}&size={size}",
        )
        chunks = result.get("data", {}).get("chunks", [])

        # Handle pagination
        total = result.get("data", {}).get("total", 0)
        if page * size < total:
            more_chunks, _ = self.get_document_chunks(
                dataset_id, document_id, page + 1, size
            )
            chunks.extend(more_chunks)

        return chunks

    def get_document_content(self, dataset_id, document_id):
        """Get full text content from a document by downloading it"""
        try:
            url = f"{self.url}/api/v1/datasets/{dataset_id}/documents/{document_id}"
            resp = self.session.get(url)

            content_type = resp.headers.get("Content-Type", "")

            if "json" in content_type:
                result = resp.json()
                doc_data = result.get("data", {})

                for field in [
                    "content",
                    "text",
                    "markdown",
                    "source_text",
                    "raw_content",
                ]:
                    content = doc_data.get(field, "")
                    if content:
                        return content

                location = doc_data.get("location")
            else:
                if resp.text:
                    return resp.text

            try:
                download_url = f"{self.url}/api/v1/datasets/{dataset_id}/documents/{document_id}/download"
                dl_resp = self.session.get(download_url)
                if dl_resp.status_code == 200 and dl_resp.text:
                    return dl_resp.text
            except Exception:
                pass

            return ""
        except Exception:
            return ""


def get_ragflow_client(settings):
    """Create Ragflow client from settings"""
    url = settings.ragflow_url or os.environ.get("RAGFLOW_URL")
    api_key = settings.ragflow_api_key or os.environ.get("RAGFLOW_API_KEY")
    allowed_datasets_str = os.environ.get("RAGFLOW_ALLOWED_DATASETS", "")
    allowed_datasets = [d.strip() for d in allowed_datasets_str.split(",") if d.strip()]

    if not url or not api_key:
        return None

    return RagflowClient(url, api_key, allowed_datasets)
