package com.vdt.dataplatform.dto;

import lombok.Data;
import java.util.List;
import java.util.Map;

@Data
public class ChatResponse {
    private String responseMessage;
    private List<Map<String, Object>> data;
}
