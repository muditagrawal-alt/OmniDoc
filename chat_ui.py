"""Enhanced chat UI with persistent storage."""
import streamlit as st
import uuid


def init_session():
    """Initialize chat session state."""
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}
    if "active_chat" not in st.session_state:
        st.session_state.active_chat = None


def render_chat_ui():
    """
    Render the main chat interface.
    Returns the user query if submitted.
    """
    init_session()

    # Check if we need to initialize a chat
    if not st.session_state.active_chat and st.session_state.conversations:
        # Use first available chat
        st.session_state.active_chat = list(st.session_state.conversations.keys())[0]
    
    if not st.session_state.active_chat:
        st.info("👈 Start a new chat from the sidebar")
        return None

    chat = st.session_state.conversations[st.session_state.active_chat]

    # Render existing messages
    for msg in chat.get("messages", []):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
            # Display images if present
            for img in msg.get("images", []):
                st.image(
                    img["image"],
                    caption=f"📄 Page {img['page']}: {img['caption']}",
                    use_container_width=True
                )

    # Chat input
    query = st.chat_input("Ask something about the document…")
    return query
