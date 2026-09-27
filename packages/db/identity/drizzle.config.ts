import { historyConfig } from '../lib/config';

// identity owns the `identity` schema: the one thing both products share.
export default historyConfig('identity', ['identity']);
