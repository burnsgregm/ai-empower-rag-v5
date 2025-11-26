# Implements Parent-Child fetching and conversational memory (last 4 turns)
import os
import logging
from flask import Flask, request, jsonify
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from langchain_google_vertexai import VertexAIEmbeddings, ChatVertexAI
from langchain.prompts import ChatPromptTemplate
from google.cloud import firestore as fs_module

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

PROJECT_ID = os.environ.get("GCP_PROJECT", "test-rag-backend-v4")
CHAT_HISTORY_COLLECTION = "rag_chat_history" 
MAX_HISTORY_TURNS = 4

db = firestore.Client(project=PROJECT_ID)
embeddings = VertexAIEmbeddings(model_name="text-embedding-004", project=PROJECT_ID)
llm = ChatVertexAI(model_name="gemini-2.5-pro", project=PROJECT_ID, temperature=0.1)

@app.route("/query", methods=["POST"])
def handle_query():
    data = request.get_json()
    if not data or "query" not in data: return jsonify({"error": "Missing 'query' field"}), 400
    
    user_query = data["query"]
    client_id = data.get("client_id", "default_client") 
    session_id = data.get("session_id", "default_session") 

    try:
        # --- 1. Retrieve Chat History ---
        history_ref = db.collection(CHAT_HISTORY_COLLECTION).document(session_id)
        history_doc = history_ref.get()
        past_conversation = ""
        
        if history_doc.exists:
            # Only pull the last 4 turns to avoid exceeding the LLM context window
            past_msgs = history_doc.to_dict().get("messages", [])[-MAX_HISTORY_TURNS:]
            for msg in past_msgs:
                past_conversation += f"{msg['role']}: {msg['content']}\n"
        
        # 2. Vector Search (Parent-Child Logic)
        query_vector = embeddings.embed_query(user_query)
        collection = db.collection("rag_children")
        vector_ref = Vector(query_vector)
        
        results = collection.where(filter=firestore.FieldFilter("client_id", "==", client_id))\
                            .find_nearest(
                                vector_field="embedding",
                                query_vector=vector_ref,
                                distance_measure=DistanceMeasure.COSINE,
                                limit=7,
                                distance_result_field="distance"
                            ).get()

        context_text = "No relevant documents found."
        if results:
            parent_ids = set(doc.to_dict()["parent_id"] for doc in results)
            parent_refs = [db.collection("rag_parents").document(pid) for pid in parent_ids]
            parent_docs = db.get_all(parent_refs)
            
            context_text = ""
            for p_doc in parent_docs:
                if p_doc.exists:
                    chunk = p_doc.to_dict()
                    context_text += f"\n[Source: {chunk['source']}, Page: {chunk['page']}]\n{chunk['content']}\n"

        # 3. Generate Answer
        prompt = ChatPromptTemplate.from_template("""
        You are an expert medical AI assistant. Answer the question strictly based on the provided context.
        Use the Chat History to understand follow-up questions or resolve ambiguous pronouns (e.g., "the two").
        
        Chat History:
        {history}
        
        Context:
        {context}
        
        Question: 
        {question}
        
        Answer:
        """)
        
        chain = prompt | llm
        response = chain.invoke({
            "context": context_text, 
            "history": past_conversation if past_conversation else "No previous conversation history.",
            "question": user_query
        })
        
        final_response = {"answer": response.content, "context_used": context_text}

        # --- 4. Save State (Update History) ---
        new_messages = [
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": response.content}
        ]
        # Use ArrayUnion to append new messages without overwriting existing history
        history_ref.set({"messages": fs_module.ArrayUnion(new_messages)}, merge=True)
        
        return jsonify(final_response), 200

    except Exception as e:
        logging.error(f"Retrieval Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)