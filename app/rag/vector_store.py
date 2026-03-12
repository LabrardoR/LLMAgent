from langchain_openai import OpenAIEmbeddings
from langchain.vectorstores import FAISS


def create_vector_store(docs):

    embedding = OpenAIEmbeddings()

    vector_store = FAISS.from_documents(
        docs,
        embedding
    )

    return vector_store