import PyPDF2
try:
    reader = PyPDF2.PdfReader(r"e:\Research Methodology\Project-Implementation\others' work\march_08.pdf")
    for i, page in enumerate(reader.pages[:3]):
        print(f"\n\n---PAGE {i}---\n\n")
        print(page.extract_text())
except Exception as e:
    print(e)
