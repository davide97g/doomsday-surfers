import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.davideghiotto.doomsdaysurfers',
  appName: 'Doomsday Surfers',
  webDir: 'dist',
  ios: {
    contentInset: 'never',
    backgroundColor: '#07040f',
    scrollEnabled: false,
  },
};

export default config;
