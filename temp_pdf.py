import tempfile

def save_uploaded_pdf(uploaded_file):
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    temp.write(uploaded_file.read())
    temp.close()
    return temp.name