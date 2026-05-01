<!DOCTYPE html>
<html>
<head>
    <title>VEXR ULTRA</title>
    <style>
        body { background: #050505; color: #f0f0f0; font-family: monospace; padding: 2rem; }
        #chat { height: 400px; overflow-y: auto; border: 1px solid #d4af37; padding: 1rem; margin-bottom: 1rem; }
        .user { color: #d4af37; }
        .assistant { color: #00d4ff; }
        input, button { background: #0f0f0f; color: #d4af37; border: 1px solid #d4af37; padding: 0.5rem; }
        input { width: 80%; }
    </style>
</head>
<body>
    <h1>⚡ VEXR ULTRA</h1>
    <div id="chat"></div>
    <input type="text" id="message" placeholder="Ask me anything...">
    <button id="send">SEND</button>

    <script>
        let token = localStorage.getItem('token');
        
        async function login() {
            const email = prompt('Email:');
            const password = prompt('Password:');
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (data.access_token) {
                token = data.access_token;
                localStorage.setItem('token', token);
                document.getElementById('chat').innerHTML += '<div>✅ Logged in!</div>';
            } else {
                document.getElementById('chat').innerHTML += '<div>❌ Login failed</div>';
            }
        }
        
        async function send() {
            const message = document.getElementById('message').value;
            if (!message) return;
            document.getElementById('chat').innerHTML += `<div class="user">You: ${message}</div>`;
            document.getElementById('message').value = '';
            
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            const data = await res.json();
            document.getElementById('chat').innerHTML += `<div class="assistant">VEXR: ${data.response}</div>`;
        }
        
        if (!token) {
            login();
        }
        
        document.getElementById('send').onclick = send;
        document.getElementById('message').onkeypress = (e) => { if (e.key === 'Enter') send(); };
    </script>
</body>
</html>
