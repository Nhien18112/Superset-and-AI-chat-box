package com.vdt.dataplatform.controller;

import com.vdt.dataplatform.dto.ChatRequest;
import com.vdt.dataplatform.service.ChatService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/chat")
public class ChatController {

    @Autowired
    private ChatService chatService;

    @PostMapping("/query")
    public ResponseEntity<?> queryChatbot(@Valid @RequestBody ChatRequest chatRequest) {
        Object principal = SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        String username;
        
        if (principal instanceof UserDetails) {
            username = ((UserDetails) principal).getUsername();
        } else {
            username = principal.toString();
        }

        try {
            // Forward request to ChatService which handles persistence and MCP context
            String llmResponse = chatService.processChat(chatRequest.getSessionId(), chatRequest.getQuery(), username);
            
            Map<String, String> response = new HashMap<>();
            response.put("reply", llmResponse);
            return ResponseEntity.ok(response);
        } catch (ResponseStatusException rse) {
            return ResponseEntity.status(rse.getStatusCode()).body(rse.getReason());
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body("Chat error: " + e.getMessage());
        }
    }
}

