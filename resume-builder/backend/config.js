const isProduction = process.env.NODE_ENV === 'production';

function requiredInProduction(name, developmentFallback = null) {
  const value = process.env[name];
  if (value) return value;
  if (isProduction) {
    throw new Error(`${name} is required when NODE_ENV=production`);
  }
  return developmentFallback;
}

module.exports = {
  JWT_SECRET: requiredInProduction(
    'JWT_SECRET',
    'resume-builder-development-only-secret'
  ),
  COZE_API_TOKEN: requiredInProduction('COZE_API_TOKEN'),
  COZE_BOT_ID: process.env.COZE_BOT_ID || '7594734352358047782',
  PORT: process.env.PORT || 3001,
};
