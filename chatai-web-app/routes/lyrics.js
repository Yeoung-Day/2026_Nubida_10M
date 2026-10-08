router.post('/generate', async (req, res) => {
    const { topic } = req.body;
    try {
        const response = await axios.post('http://ollama:11434/api/generate', {
            model: 'llama3.2:1b', // 가벼운 모델 강제 지정
            prompt: `주제: ${topic}. 이 주제로 힙합 가사 8마디를 라임 맞춰서 써. 가사만 출력해.`,
            stream: false // 스트림을 끄면 한 번에 전체 문장을 받아와서 더 빠르게 화면에 표시됩니다.
        });
        res.json({ lyrics: response.data.response });
    } catch (err) {
        res.status(500).send('서버 바쁨');
    }
});