document.addEventListener("DOMContentLoaded", () => {
    // DOM 元素
    const authContainer = document.getElementById("auth-container");
    const chatContainer = document.getElementById("chat-container");
    const authForm = document.getElementById("auth-form");
    const authTitle = document.getElementById("auth-title");
    const authButton = document.getElementById("auth-button");
    const toggleLink = document.getElementById("toggle-link");
    const toggleAuthModeText = document.getElementById("toggle-auth-mode");
    const logoutButton = document.getElementById("logout-button");
    const conversationsList = document.getElementById("conversations-list");
    const newChatButton = document.getElementById("new-chat-button");
    const usernameDisplay = document.getElementById("username-display");
    const chatMessages = document.getElementById("chat-messages");
    const chatInput = document.getElementById("chat-input");
    const sendButton = document.getElementById("send-button");

    // API 地址
    const API_BASE_URL = "http://127.0.0.1:8000/api";

    // 应用状态
    let isLoginMode = true;
    let token = localStorage.getItem("token");
    let user = JSON.parse(localStorage.getItem("user"));
    let conversationId = null;
    let conversations = [];

    // 更新认证表单的 UI
    const updateAuthUI = () => {
        authTitle.textContent = isLoginMode ? "登录" : "注册";
        authButton.textContent = isLoginMode ? "登录" : "注册";
        toggleAuthModeText.innerHTML = isLoginMode ? '没有账户？ <a href="#" id="toggle-link">立即注册</a>' : '已有账户？ <a href="#" id="toggle-link">立即登录</a>';
        document.getElementById("toggle-link").addEventListener("click", toggleAuthMode);
    };

    // 切换登录/注册模式
    const toggleAuthMode = (e) => {
        e.preventDefault();
        isLoginMode = !isLoginMode;
        updateAuthUI();
    };

    // 显示聊天界面
    const showChat = () => {
        authContainer.classList.add("hidden");
        chatContainer.classList.remove("hidden");
        usernameDisplay.textContent = user.username || user.account;
        loadConversations();
        startNewChat();
    };

    // 显示认证界面
    const showAuth = () => {
        authContainer.classList.remove("hidden");
        chatContainer.classList.add("hidden");
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        token = null;
        user = null;
    };

    // 处理认证（登录/注册）
    const handleAuth = async (e) => {
        e.preventDefault();
        const account = document.getElementById("account").value;
        const password = document.getElementById("password").value;
        const endpoint = isLoginMode ? "/user/login" : "/user/register";

        const options = {
            method: "POST",
            headers: {
                "Content-Type": isLoginMode ? "application/x-www-form-urlencoded" : "application/json",
            },
            body: isLoginMode ? `username=${encodeURIComponent(account)}&password=${encodeURIComponent(password)}` : JSON.stringify({ account, password }),
        };

        try {
            const response = await fetch(API_BASE_URL + endpoint, options);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "操作失败");
            }

            token = data.access_token;
            user = data.user;
            localStorage.setItem("token", token);
            localStorage.setItem("user", JSON.stringify(user));
            showChat();
        } catch (error) {
            alert(`错误: ${error.message}`);
        }
    };

    // 加载会话列表
    const loadConversations = async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/chat/conversations`, {
                headers: { "Authorization": `Bearer ${token}` },
            });
            if (!response.ok) throw new Error("无法加载会话列表");
            conversations = await response.json();
            renderConversations();
        } catch (error) {
            console.error(error.message);
        }
    };

    // 渲染会话列表
    const renderConversations = () => {
        conversationsList.innerHTML = "";
        conversations.forEach(conv => {
            const item = document.createElement("div");
            item.classList.add("conversation-item");
            item.textContent = conv.title;
            item.dataset.id = conv.conversation_id;
            if (conv.conversation_id === conversationId) {
                item.classList.add("active");
            }
            item.addEventListener("click", () => selectConversation(conv.conversation_id));
            item.addEventListener("dblclick", () => enableRename(item, conv.conversation_id));
            conversationsList.appendChild(item);
        });
    };

    // 启用重命名
    const enableRename = (item, id) => {
        const originalTitle = item.textContent;
        const input = document.createElement("input");
        input.type = "text";
        input.value = originalTitle;
        input.classList.add("rename-input");
        item.innerHTML = "";
        item.appendChild(input);
        input.focus();

        input.addEventListener("blur", () => {
            item.textContent = originalTitle; // 取消编辑
        });

        input.addEventListener("keypress", async (e) => {
            if (e.key === "Enter") {
                const newTitle = input.value.trim();
                if (newTitle && newTitle !== originalTitle) {
                    await renameConversation(id, newTitle, item);
                } else {
                    item.textContent = originalTitle;
                }
            }
        });
    };

    // 重命名会话
    const renameConversation = async (id, newTitle, item) => {
        try {
            const response = await fetch(`${API_BASE_URL}/chat/conversations/${id}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`,
                },
                body: JSON.stringify({ title: newTitle }),
            });
            if (!response.ok) throw new Error("重命名失败");
            item.textContent = newTitle;
            // 更新内存中的会话标题
            const conv = conversations.find(c => c.conversation_id === id);
            if (conv) conv.title = newTitle;
        } catch (error) {
            alert(error.message);
            item.textContent = (conversations.find(c => c.conversation_id === id) || {}).title || "未知会话";
        }
    };

    // 选择一个会话
    const selectConversation = async (id) => {
        if (conversationId === id) return;
        conversationId = id;
        chatMessages.innerHTML = "加载中...";
        try {
            const response = await fetch(`${API_BASE_URL}/chat/conversations/${id}`, {
                headers: { "Authorization": `Bearer ${token}` },
            });
            if (!response.ok) throw new Error("无法加载消息");
            const messages = await response.json();
            chatMessages.innerHTML = "";
            messages.forEach(msg => appendMessage(msg.role, msg.content));
            renderConversations(); // 更新高亮状态
        } catch (error) {
            chatMessages.innerHTML = `<div class="message assistant"><div class="content">${error.message}</div></div>`;
        }
    };

    // 开始新聊天
    const startNewChat = () => {
        conversationId = null;
        chatMessages.innerHTML = "";
        chatInput.value = "";
        renderConversations(); // 清除高亮
    };

    // 发送消息（流式 Fetch）
    const sendMessage = async () => {
        const content = chatInput.value.trim();
        if (!content) return;

        appendMessage("user", content);
        chatInput.value = "";

        const assistantMessageDiv = appendMessage("assistant", "");
        const assistantContentDiv = assistantMessageDiv.querySelector(".content");

        try {
            const response = await fetch(`${API_BASE_URL}/chat/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`,
                },
                body: JSON.stringify({
                    conversation_id: conversationId,
                    messages: [{ role: "user", content: content }],
                }),
            });

            if (!response.ok) {
                throw new Error("网络响应错误");
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                buffer += chunk;

                let index;
                while ((index = buffer.indexOf("\n\n")) !== -1) {
                    const rawEvent = buffer.slice(0, index);
                    buffer = buffer.slice(index + 2);

                    const lines = rawEvent.split("\n");
                    for (const line of lines) {
                        if (line.startsWith("data: ")) {
                            const jsonStr = line.substring(6);
                            if (jsonStr.trim()) {
                                const data = JSON.parse(jsonStr);
                                if (data.conversation_id) {
                                    if (!conversationId) {
                                        conversationId = data.conversation_id;
                                        loadConversations();
                                    }
                                }
                                if (data.content) {
                                    assistantContentDiv.textContent += data.content;
                                    chatMessages.scrollTop = chatMessages.scrollHeight;
                                }
                                if (data.error) {
                                    assistantContentDiv.textContent = `错误: ${data.error}`;
                                    return;
                                }
                            }
                        }
                    }
                }
            }
        } catch (error) {
            assistantContentDiv.textContent = `请求失败: ${error.message}`;
        }
    };

    // 将消息添加到聊天窗口
    const appendMessage = (role, content) => {
        const messageDiv = document.createElement("div");
        messageDiv.classList.add("message", role);

        const avatarDiv = document.createElement("div");
        avatarDiv.classList.add("avatar");

        const contentDiv = document.createElement("div");
        contentDiv.classList.add("content");
        contentDiv.textContent = content;

        messageDiv.appendChild(avatarDiv);
        messageDiv.appendChild(contentDiv);
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    };

    // 初始化
    const init = () => {
        if (token && user) {
            showChat();
        } else {
            showAuth();
        }
        updateAuthUI();
        authForm.addEventListener("submit", handleAuth);
        logoutButton.addEventListener("click", showAuth);
        newChatButton.addEventListener("click", startNewChat);
        sendButton.addEventListener("click", sendMessage);
        chatInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") sendMessage();
        });
    };

    init();
});
