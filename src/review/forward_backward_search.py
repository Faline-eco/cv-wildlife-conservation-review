import csv
import socket
from time import sleep
from typing import Optional, Tuple
import time
import bibtexparser
import requests
from bibtexparser.bibdatabase import BibDatabase
from scholarly import ProxyGenerator, scholarly
from scholarly.data_types import ProxyMode
import json

# class TorProxy:
#     """
#     Use with: docker container run -it -p 8118:8118 -p 9051:9051 -e PASSWORD="secure123" dperson/torproxy
#     """
#     def __init__(self):
#         self.user_agent = "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:77.0) Gecko/20100101 Firefox/77.0"
#         self.max_calls_until_renew = 10
#         self.proxy_password = "secure123"
#         self.proxy_url = "127.0.0.1"
#         self.proxy_socket_port = 9051
#         self.proxy_http_port = 8118
#         self.__count_http_calls = 0
#         self.__proxies = {
#             'http': f'{self.proxy_url}:{self.proxy_http_port}',
#             'https': f'{self.proxy_url}:{self.proxy_http_port}'
#         }
#         self.proxy_mode = ProxyMode.TOR_EXTERNAL
#
#     def renew_proxy(self):
#         with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#             s.connect((self.proxy_url, self.proxy_socket_port))
#             s.send(f"authenticate \"{self.proxy_password}\"\r\n".encode())
#             s.send(f"SIGNAL NEWNYM\r\n".encode())
#
#     def ensure_client(self):
#         self.__count_http_calls += 1
#         if self.__count_http_calls % self.max_calls_until_renew == 0:
#             self.renew_proxy()
#
#     def get(self, url: str) -> requests.Response:
#         self.ensure_client()
#         x = requests.get(url, proxies=self.__proxies, allow_redirects=True)
#         return x
#
#     def get_session(self):
#         self.ensure_client()
#         session = requests.Session()
#         session.proxies = self.__proxies
#         return session

def get_bib_tex(doi_address: str, doi2bib_base_url: str) -> Tuple[Optional[str], Optional[BibDatabase]]:
    doi_address = doi_address.strip()
    if not doi_address.startswith("https://doi.org/"):
        print(f"No doi {doi_address}")
        return None, None
    doi = doi_address.replace("https://doi.org/", "")
    url = f'{doi2bib_base_url}/?url={doi}'
    response = requests.get(url)
    library = bibtexparser.loads(response.text)
    library.comments = {}
    for entry in library.entries:
        if "doi" not in entry and "url" not in entry:
            print(f"No doi or url in parsed bibtext for {doi}")
            entry["doi"] = doi
            entry["url"] = doi_address
    return doi, library

if __name__ == '__main__':
    """
    Start doi2bib docker container first: docker run -p 8080:8080 doi2bib-web
    You can also start/activate the tor proxy: docker container run -it -p 8118:8118 -p 9051:9051 -e PASSWORD="secure123" dperson/torproxy
    
    """
    # proxy = TorProxy()
    # scholarly.use_proxy(proxy)
    doi2bib_base_url = "http://localhost:8080"
    input_file_path = r"C:\D\Projects\LiteratureReview\review_filtered.csv"
    output_file_path = r"C:\D\Projects\LiteratureReview\review_filtered_output.csv"
    bibtex = r"C:\D\Projects\LiteratureReview\bibliogrpahy.tex"
    min_year = 2014
    ignore_first_line_in_input = False
    #################################
    unique_ids = set()

    max_citations = 0
    max_citations_publication = None

    bibtex_parser = bibtexparser.bparser.BibTexParser()

    is_first_line = True
    cnt = 0
    api_limit_per_second = 6
    total_start = time.time()
    with (open(input_file_path, encoding='utf-8-sig') as input_file,
          open(bibtex, "w", encoding='utf-8') as bibtex_file,
          open(output_file_path, "w", newline='', encoding="utf-8") as target_file):
        spamwriter = csv.writer(target_file, delimiter=';', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        spamwriter.writerow(("doi", "type"))
        for outer_cnt, entry in enumerate(csv.reader(input_file, delimiter=';', quotechar='|', quoting=csv.QUOTE_MINIMAL), start=1):
            if is_first_line:
                is_first_line = False
                if ignore_first_line_in_input:
                    continue
            doi_address = entry[0]
            start = time.time()
            print(f"{outer_cnt}. Parsing {doi_address}...")
            cnt += 1
            doi, library = get_bib_tex(doi_address, doi2bib_base_url)
            if doi in unique_ids:
                print(f"----- Already scrapped {doi}")
                continue
            unique_ids.add(doi)

            spamwriter.writerow((doi, "manual"))

            if library is None or len(library.entries) != 1:
                print(f"--- Problem parsing {doi}")
                continue

            #entry = library.entries[0]
            year = library.entries[0].get("year")
            if year is None:
                print(f"----- Skipping because of unknown year")
                continue
            year = int(year)
            if year < min_year:
                print(f"--- Skipping because too old, release in {year}")
                continue

            #title = entry["title"]
            # bibtex_file.writelines(bibtexparser.dumps(library))
            # bibtex_file.flush()
            if cnt >= api_limit_per_second - 1:
                cnt = 0
                sleep(1)

            cnt += 1
            cited_by_result = requests.get(f"https://opencitations.net/index/coci/api/v1/citations/{doi}")
            cited_by_articles = json.loads(cited_by_result.content)
            # x = FullDoc(doi=doi)
            # x.read(scopus_client)
            l = len(cited_by_articles)
            if l > max_citations:
                max_citations = l
                max_citations_publication = doi
            # bibtex_file.write(f"{doi}\n")
            references_result = requests.get(f"https://opencitations.net/index/coci/api/v1/references/{doi}")
            referenced_articles = json.loads(references_result.content)
            for inner_cnt, article in enumerate(referenced_articles, start=1):
                referenced_article_doi = f"https://doi.org/{article['cited']}"
                print(f"--- {outer_cnt}.b.{inner_cnt}. Parsing {referenced_article_doi} in Backward search...")
                cnt += 1
                backward_doi, library = get_bib_tex(referenced_article_doi, doi2bib_base_url)
                if backward_doi in unique_ids:
                    print(f"----- Already scrapped {backward_doi}")
                    continue
                unique_ids.add(backward_doi)
                if library is None or len(library.entries) != 1:
                    print(f"----- Problem parsing {referenced_article_doi}")
                    continue
                year = library.entries[0].get("year")
                if year is None:
                    print(f"----- Skipping because of unknown year")
                    continue
                year = int(year)
                if year < min_year:
                    print(f"----- Skipping because too old, release in {year}")
                    continue
                bibtex_file.writelines(bibtexparser.dumps(library))
                spamwriter.writerow((backward_doi, "backward"))
            for inner_cnt, article in enumerate(cited_by_articles, start=1):
                citing_article_doi = f"https://doi.org/{article['citing']}"
                print(f"--- {outer_cnt}.f.{inner_cnt}. Parsing {citing_article_doi} in Forward search...")
                cnt += 1
                forward_doi, library = get_bib_tex(citing_article_doi, doi2bib_base_url)
                if forward_doi in unique_ids:
                    print(f"----- Already scrapped {forward_doi}")
                    continue
                unique_ids.add(forward_doi)
                if library is None or len(library.entries) != 1:
                    print(f"----- Problem parsing {citing_article_doi}")
                    continue
                year = library.entries[0].get("year")
                if year is None:
                    print(f"----- Skipping because of unknown year")
                    continue
                year = int(year)
                if year < min_year:
                    print(f"----- Skipping because too old, release in {year}")
                    continue
                bibtex_file.writelines(bibtexparser.dumps(library))
                spamwriter.writerow((forward_doi, "forward"))
            #     print()
            #     citing_url = f'{doi2bib_base_url}/?url={doi}'
            #     citing_response = requests.get(citing_url)
            #     citing_library = bibtexparser.loads(citing_response.text)
            #     print()
            # references_result = requests.get(f"https://opencitations.net/index/coci/api/v1/references/{doi}")
            # referenced_articles = json.loads(references_result.content)
            # # x = FullDoc(doi=doi)
            # # x.read(scopus_client)
            # for article in referenced_articles:
            #     referenced_article_doi = article["cited"]
            #     print()
            #     cited_url = f'{doi2bib_base_url}/?url={doi}'
            #     cited_response = requests.get(cited_url)
            #     cited_library = bibtexparser.loads(cited_response.text)
            #     print()
            # forward search via google scholar
            # search_query = scholarly.search_pubs(title)
            # for res in search_query: # there should be only one
            #     print()
            end = time.time()
            print(f"Parsed {doi_address} and backward/forward search in {end - start} sec...")
            print(f"---------------------------------")
            print(f"---------------------------------")
            print(f"---------------------------------")

    print(f"{max_citations_publication} {max_citations}")
    total_end = time.time()
    print(f"Parsed {cnt} entries in {total_end - total_start} sec...")
