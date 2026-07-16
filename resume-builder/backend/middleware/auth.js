const jwt = require('jsonwebtoken');
const config = require('../config');

/**
 * JWT 认证中间件
 * 从 Authorization header 提取 Bearer token 并校验
 * 校验通过后将用户信息附加到 req.user
 */
function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: '未登录，请先登录' });
  }

  const token = authHeader.replace('Bearer ', '');

  try {
    const decoded = jwt.verify(token, config.JWT_SECRET);
    req.user = decoded;
    next();
  } catch (err) {
    return res.status(401).json({ error: '令牌无效或已过期，请重新登录' });
  }
}

module.exports = authMiddleware;
