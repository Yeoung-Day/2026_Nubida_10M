router.post('/login', async (req, res) => {
    const { studentId, name } = req.body;
    // 간단히 DB에 이 정보가 있는지 확인하거나, 없으면 바로 등록하고 로그인 처리
    try {
        await db.query('INSERT IGNORE INTO students (username, name) VALUES (?, ?)', [studentId, name]);
        req.session.studentId = studentId;
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: '로그인 실패' });
    }
});