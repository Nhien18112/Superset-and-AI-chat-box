package com.vdt.dataplatform.service;

import com.vdt.dataplatform.model.ChatMessage;
import com.vdt.dataplatform.model.ChatSession;
import com.vdt.dataplatform.repository.ChatMessageRepository;
import com.vdt.dataplatform.repository.ChatSessionRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
public class ChatService {

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Value("${superset.automation-worker-url:http://python-worker:8000}")
    private String pythonWorkerUrl;

    private final RestTemplate restTemplate = new RestTemplate();

    public String processChat(String sessionId, String query, String username) {
        // Security check
        Optional<ChatSession> sessionOpt = chatSessionRepository.findById(sessionId);
        if (sessionOpt.isPresent()) {
            if (!sessionOpt.get().getUsername().equals(username)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Access Denied: Session belongs to another user.");
            }
        } else {
            ChatSession newSession = new ChatSession();
            newSession.setSessionId(sessionId);
            newSession.setUsername(username);
            chatSessionRepository.save(newSession);
        }

        // Fetch history
        List<ChatMessage> history = chatMessageRepository.findBySessionIdOrderByCreatedAtAsc(sessionId);

        // Map history for Python MCP payload
        List<Map<String, Object>> formattedHistory = new ArrayList<>();
        for (ChatMessage msg : history) {
            Map<String, Object> hm = new HashMap<>();
            hm.put("text", msg.getContent());
            hm.put("isUser", "USER".equals(msg.getSenderType()));
            formattedHistory.add(hm);
        }

        // Save incoming user message
        ChatMessage userMsg = new ChatMessage();
        userMsg.setSessionId(sessionId);
        userMsg.setSenderType("USER");
        userMsg.setContent(query);
        chatMessageRepository.save(userMsg);

        // Execute MCP API
        Map<String, Object> payload = new HashMap<>();
        payload.put("query", query);
        payload.put("username", username);
        payload.put("history", formattedHistory);

        String aiResponse = "Error connecting to AI Agent.";
        try {
            Map<String, Object> response = restTemplate.postForObject(pythonWorkerUrl + "/api/chat", payload, Map.class);
            if (response != null && response.containsKey("reply")) {
                aiResponse = (String) response.get("reply");
            }
        } catch (Exception e) {
            aiResponse = "Error from Python Worker: " + e.getMessage();
        }

        // Save AI response
        ChatMessage aiMsg = new ChatMessage();
        aiMsg.setSessionId(sessionId);
        aiMsg.setSenderType("AI");
        aiMsg.setContent(aiResponse);
        chatMessageRepository.save(aiMsg);

        return aiResponse;
    }
}
