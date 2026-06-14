package com.vdt.dataplatform.repository;

import com.vdt.dataplatform.model.ChatSession;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ChatSessionRepository extends JpaRepository<ChatSession, String> {
    List<ChatSession> findByUsernameOrderByCreatedAtDesc(String username);
}
