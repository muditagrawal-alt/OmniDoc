import streamlit as st
import uuid


def init_session():
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}

    if "active_chat" not in st.session_state:
        st.session_state.active_chat = None


def render_chat_ui():
    init_session()

    # ---------- SIDEBAR ----------
    with st.sidebar:
        st.markdown("### 💬 Chat History")

        if st.button("➕ New Chat"):
            chat_id = str(uuid.uuid4())
            st.session_state.conversations[chat_id] = {
                "title": "New conversation",
                "messages": []
            }
            st.session_state.active_chat = chat_id

        st.divider()

        for chat_id, chat in st.session_state.conversations.items():
            if st.button(chat["title"], key=chat_id):
                st.session_state.active_chat = chat_id

    # ---------- MAIN CHAT ----------
    if not st.session_state.active_chat:
        st.info("Start a new chat to begin")
        return None

    chat = st.session_state.conversations[st.session_state.active_chat]

    # Render messages
    for msg in chat["messages"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            for img in msg.get("images", []):
                st.image(
                    img["image"],
                    caption=f"Page {img['page']}: {img['caption']}",
                    use_container_width=True
                )

    query = st.chat_input("Ask something about the document…")
    return query