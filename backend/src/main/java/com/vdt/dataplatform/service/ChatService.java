package com.vdt.dataplatform.service;

import com.vdt.dataplatform.model.ChatMessage;
import com.vdt.dataplatform.model.ChatSession;
import com.vdt.dataplatform.repository.ChatMessageRepository;
import com.vdt.dataplatform.repository.ChatSessionRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Optional;

@Service
public class ChatService {

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private CodexService codexService;

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

        // Save incoming user message
        ChatMessage userMsg = new ChatMessage();
        userMsg.setSessionId(sessionId);
        userMsg.setSenderType("USER");
        userMsg.setContent(query);
        chatMessageRepository.save(userMsg);

        // Execute Codex API with context
        String aiResponse = codexService.processUserQueryWithHistory(query, username, history);

        // Save AI response
        ChatMessage aiMsg = new ChatMessage();
        aiMsg.setSessionId(sessionId);
        aiMsg.setSenderType("AI");
        aiMsg.setContent(aiResponse);
        chatMessageRepository.save(aiMsg);

        return aiResponse;
    }
}
