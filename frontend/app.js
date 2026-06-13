const customerSelect = document.getElementById("customer-select");
const customerInfo = document.getElementById("customer-info");
const chatWindow = document.getElementById("chat-window");
const messageInput = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const muteBtn = document.getElementById("mute-btn");
const micStatus = document.getElementById("mic-status");

let customers = [];
let speechEnabled = true;
let recognition = null;

async function loadCustomers() {
  try {
    const res = await fetch("/customers");
    customers = await res.json();
    customerSelect.innerHTML = '<option value="">— Select a customer —</option>';
    customers.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c.customer_id;
      opt.textContent = `${c.customer_id} — ${c.name}`;
      customerSelect.appendChild(opt);
    });
  } catch {
    customerSelect.innerHTML = '<option value="">Failed to load customers</option>';
  }
}

customerSelect.addEventListener("change", () => {
  const id = customerSelect.value;
  const c = customers.find((x) => x.customer_id === id);
  if (!c) {
    customerInfo.innerHTML = "";
    return;
  }
  customerInfo.innerHTML = `
    <p><strong>${c.name}</strong></p>
    <p>${c.email}</p>
    <p>Tier: ${c.loyalty_tier}</p>
    <p>Orders: ${c.total_orders}</p>
  `;
});

function appendMessage(text, role) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.textContent = text;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function speak(text) {
  if (!speechEnabled || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

async function sendMessage() {
  const customerId = customerSelect.value;
  const message = messageInput.value.trim();

  if (!customerId) {
    appendMessage("Please select a customer first.", "system");
    return;
  }
  if (!message) return;

  appendMessage(message, "user");
  messageInput.value = "";
  sendBtn.disabled = true;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id: customerId, message }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${res.status}`);
    }

    const data = await res.json();
    appendMessage(data.response, "agent");
    speak(data.response);
  } catch (err) {
    appendMessage(`Error: ${err.message}`, "system");
  } finally {
    sendBtn.disabled = false;
    messageInput.focus();
  }
}

sendBtn.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

muteBtn.addEventListener("click", () => {
  speechEnabled = !speechEnabled;
  muteBtn.textContent = speechEnabled ? "🔊" : "🔇";
  muteBtn.classList.toggle("active", !speechEnabled);
  if (!speechEnabled) window.speechSynthesis?.cancel();
});

function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micBtn.disabled = true;
    micBtn.title = "Speech recognition not supported in this browser";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    micBtn.classList.add("active");
    micStatus.textContent = "Listening…";
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    messageInput.value = transcript;
    micStatus.textContent = `Heard: "${transcript}"`;
    sendMessage();
  };

  recognition.onerror = (event) => {
    micStatus.textContent = `Mic error: ${event.error}`;
    micBtn.classList.remove("active");
  };

  recognition.onend = () => {
    micBtn.classList.remove("active");
    if (!micStatus.textContent.startsWith("Heard")) {
      micStatus.textContent = "";
    }
  };

  micBtn.addEventListener("click", () => {
    if (!customerSelect.value) {
      appendMessage("Please select a customer first.", "system");
      return;
    }
    try {
      recognition.start();
    } catch {
      micStatus.textContent = "Mic already active";
    }
  });
}

loadCustomers();
setupSpeechRecognition();
