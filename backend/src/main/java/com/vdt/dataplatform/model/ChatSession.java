package com.vdt.dataplatform.model;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.time.LocalDateTime;

@Entity
@Table(name = "chat_sessions")
@Data
@NoArgsConstructor
public class ChatSession {
    @Id
    @Column(name = "session_id", length = 50)
    private String sessionId;

    @Column(name = "username", length = 50)
    private String username;

    @Column(name = "created_at", insertable = false, updatable = false)
    private LocalDateTime createdAt;
}
