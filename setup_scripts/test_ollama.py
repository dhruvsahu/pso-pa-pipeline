from ollama import chat

response = chat(
    model='qwen2.5:7b',
    messages=[
        {
            'role': 'user',
            'content': 'Explain prior authorization in 3 bullet points.'
        }
    ]
)

print(response['message']['content'])