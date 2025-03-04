import unittest

import torch
import torchaudio.prototype.functional as F
from torchaudio_unittest.common_utils import nested_params, TestBaseMixin, torch_script


class TorchScriptConsistencyTestImpl(TestBaseMixin):
    def _assert_consistency(self, func, inputs, shape_only=False):
        inputs_ = []
        for i in inputs:
            if torch.is_tensor(i):
                i = i.to(device=self.device, dtype=self.dtype)
            inputs_.append(i)
        ts_func = torch_script(func)

        torch.random.manual_seed(40)
        output = func(*inputs_)

        torch.random.manual_seed(40)
        ts_output = ts_func(*inputs_)

        if shape_only:
            ts_output = ts_output.shape
            output = output.shape
        self.assertEqual(ts_output, output)

    @nested_params(
        ["convolve", "fftconvolve"],
        ["full", "valid", "same"],
    )
    def test_convolve(self, fn, mode):
        leading_dims = (2, 3, 2)
        L_x, L_y = 32, 55
        x = torch.rand(*leading_dims, L_x, dtype=self.dtype, device=self.device)
        y = torch.rand(*leading_dims, L_y, dtype=self.dtype, device=self.device)

        self._assert_consistency(getattr(F, fn), (x, y, mode))

    def test_add_noise(self):
        leading_dims = (2, 3)
        L = 31

        waveform = torch.rand(*leading_dims, L, dtype=self.dtype, device=self.device, requires_grad=True)
        noise = torch.rand(*leading_dims, L, dtype=self.dtype, device=self.device, requires_grad=True)
        lengths = torch.rand(*leading_dims, dtype=self.dtype, device=self.device, requires_grad=True)
        snr = torch.rand(*leading_dims, dtype=self.dtype, device=self.device, requires_grad=True) * 10

        self._assert_consistency(F.add_noise, (waveform, noise, lengths, snr))

    def test_barkscale_fbanks(self):
        if self.device != torch.device("cpu"):
            raise unittest.SkipTest("No need to perform test on device other than CPU")

        n_stft = 100
        f_min = 0.0
        f_max = 20.0
        n_barks = 10
        sample_rate = 16000
        self._assert_consistency(F.barkscale_fbanks, (n_stft, f_min, f_max, n_barks, sample_rate, "traunmuller"))

    def test_oscillator_bank(self):
        num_frames, num_pitches, sample_rate = 8000, 8, 8000
        freq = torch.rand((num_frames, num_pitches), dtype=self.dtype, device=self.device)
        amps = torch.ones_like(freq)

        self._assert_consistency(F.oscillator_bank, (freq, amps, sample_rate, "sum"))

    def test_extend_pitch(self):
        num_frames = 5
        input = torch.ones((num_frames, 1), device=self.device, dtype=self.dtype)

        num_pitches = 7
        pattern = [i + 1.0 for i in range(num_pitches)]

        self._assert_consistency(F.extend_pitch, (input, num_pitches))
        self._assert_consistency(F.extend_pitch, (input, pattern))
        self._assert_consistency(F.extend_pitch, (input, torch.tensor(pattern)))

    def test_sinc_ir(self):
        cutoff = torch.tensor([0, 0.5, 1.0], device=self.device, dtype=self.dtype)
        self._assert_consistency(F.sinc_impulse_response, (cutoff, 513, False))
        self._assert_consistency(F.sinc_impulse_response, (cutoff, 513, True))

    def test_speed(self):
        leading_dims = (3, 2)
        T = 200
        waveform = torch.rand(*leading_dims, T, dtype=self.dtype, device=self.device, requires_grad=True)
        lengths = torch.randint(1, T, leading_dims, dtype=self.dtype, device=self.device)
        self._assert_consistency(F.speed, (waveform, lengths, 1000, 1.1))
