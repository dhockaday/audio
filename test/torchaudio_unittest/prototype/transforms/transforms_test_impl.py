import math
import random
from unittest.mock import patch

import numpy as np
import torch
import torchaudio.prototype.transforms as T
from scipy import signal
from torchaudio_unittest.common_utils import get_spectrogram, get_whitenoise, nested_params, TestBaseMixin


def _get_ratio(mat):
    return (mat.sum() / mat.numel()).item()


class TransformsTestImpl(TestBaseMixin):
    @nested_params(
        [(10, 4), (4, 3, 1, 2), (2,), ()],
        [(100, 43), (21, 45)],
        ["full", "valid", "same"],
    )
    def test_Convolve(self, leading_dims, lengths, mode):
        """Check that convolve returns values identical to those that SciPy produces."""
        L_x, L_y = lengths

        x = torch.rand(*(leading_dims + (L_x,)), dtype=self.dtype, device=self.device)
        y = torch.rand(*(leading_dims + (L_y,)), dtype=self.dtype, device=self.device)

        convolve = T.Convolve(mode=mode).to(self.device)
        actual = convolve(x, y)

        num_signals = torch.tensor(leading_dims).prod() if leading_dims else 1
        x_reshaped = x.reshape((num_signals, L_x))
        y_reshaped = y.reshape((num_signals, L_y))
        expected = [
            signal.convolve(x_reshaped[i].detach().cpu().numpy(), y_reshaped[i].detach().cpu().numpy(), mode=mode)
            for i in range(num_signals)
        ]
        expected = torch.tensor(np.array(expected))
        expected = expected.reshape(leading_dims + (-1,))

        self.assertEqual(expected, actual)

    @nested_params(
        [(10, 4), (4, 3, 1, 2), (2,), ()],
        [(100, 43), (21, 45)],
        ["full", "valid", "same"],
    )
    def test_FFTConvolve(self, leading_dims, lengths, mode):
        """Check that fftconvolve returns values identical to those that SciPy produces."""
        L_x, L_y = lengths

        x = torch.rand(*(leading_dims + (L_x,)), dtype=self.dtype, device=self.device)
        y = torch.rand(*(leading_dims + (L_y,)), dtype=self.dtype, device=self.device)

        convolve = T.FFTConvolve(mode=mode).to(self.device)
        actual = convolve(x, y)

        expected = signal.fftconvolve(x.detach().cpu().numpy(), y.detach().cpu().numpy(), axes=-1, mode=mode)
        expected = torch.tensor(expected)

        self.assertEqual(expected, actual)

    def test_InverseBarkScale(self):
        """Gauge the quality of InverseBarkScale transform.

        As InverseBarkScale is currently implemented with
        random initialization + iterative optimization,
        it is not practically possible to assert the difference between
        the estimated spectrogram and the original spectrogram as a whole.
        Estimated spectrogram has very huge descrepency locally.
        Thus in this test we gauge what percentage of elements are bellow
        certain tolerance.
        At the moment, the quality of estimated spectrogram is worse than the
        one obtained for Inverse MelScale.
        When implementation is changed in a way it makes the quality even worse,
        this test will fail.
        """
        n_fft = 400
        power = 1
        n_barks = 64
        sample_rate = 8000

        n_stft = n_fft // 2 + 1

        # Generate reference spectrogram and input mel-scaled spectrogram
        expected = get_spectrogram(
            get_whitenoise(sample_rate=sample_rate, duration=1, n_channels=2), n_fft=n_fft, power=power
        ).to(self.device, self.dtype)
        input = T.BarkScale(n_barks=n_barks, sample_rate=sample_rate, n_stft=n_stft).to(self.device, self.dtype)(
            expected
        )

        # Run transform
        transform = T.InverseBarkScale(n_stft, n_barks=n_barks, sample_rate=sample_rate).to(self.device, self.dtype)
        result = transform(input)

        # Compare
        epsilon = 1e-60
        relative_diff = torch.abs((result - expected) / (expected + epsilon))

        for tol in [1e-1, 1e-3, 1e-5, 1e-10]:
            print(f"Ratio of relative diff smaller than {tol:e} is " f"{_get_ratio(relative_diff < tol)}")
        assert _get_ratio(relative_diff < 1e-1) > 0.2
        assert _get_ratio(relative_diff < 1e-3) > 2e-3

    def test_Speed_identity(self):
        """speed of 1.0 does not alter input waveform and length"""
        leading_dims = (5, 4, 2)
        time = 1000
        waveform = torch.rand(*leading_dims, time)
        lengths = torch.randint(1, 1000, leading_dims)
        speed = T.Speed(1000, 1.0)
        actual_waveform, actual_lengths = speed(waveform, lengths)
        self.assertEqual(waveform, actual_waveform)
        self.assertEqual(lengths, actual_lengths)

    @nested_params(
        [0.8, 1.1, 1.2],
    )
    def test_Speed_accuracy(self, factor):
        """sinusoidal waveform is properly compressed by factor"""
        n_to_trim = 20

        sample_rate = 1000
        freq = 2
        times = torch.arange(0, 5, 1.0 / sample_rate)
        waveform = torch.cos(2 * math.pi * freq * times).unsqueeze(0).to(self.device, self.dtype)
        lengths = torch.tensor([waveform.size(1)])

        speed = T.Speed(sample_rate, factor).to(self.device, self.dtype)
        output, output_lengths = speed(waveform, lengths)
        self.assertEqual(output.size(1), output_lengths[0])

        new_times = torch.arange(0, 5 / factor, 1.0 / sample_rate)
        expected_waveform = torch.cos(2 * math.pi * freq * factor * new_times).unsqueeze(0).to(self.device, self.dtype)

        self.assertEqual(
            expected_waveform[..., n_to_trim:-n_to_trim], output[..., n_to_trim:-n_to_trim], atol=1e-1, rtol=1e-4
        )

    def test_SpeedPerturbation(self):
        """sinusoidal waveform is properly compressed by sampled factors"""
        n_to_trim = 20

        sample_rate = 1000
        freq = 2
        times = torch.arange(0, 5, 1.0 / sample_rate)
        waveform = torch.cos(2 * math.pi * freq * times).unsqueeze(0).to(self.device, self.dtype)
        lengths = torch.tensor([waveform.size(1)])

        factors = [0.8, 1.1, 1.0]
        indices = random.choices(range(len(factors)), k=5)

        speed_perturb = T.SpeedPerturbation(sample_rate, factors).to(self.device, self.dtype)

        with patch("torch.randint", side_effect=indices):
            for idx in indices:
                output, output_lengths = speed_perturb(waveform, lengths)
                self.assertEqual(output.size(1), output_lengths[0])
                factor = factors[idx]
                new_times = torch.arange(0, 5 / factor, 1.0 / sample_rate)
                expected_waveform = (
                    torch.cos(2 * math.pi * freq * factor * new_times).unsqueeze(0).to(self.device, self.dtype)
                )
                self.assertEqual(
                    expected_waveform[..., n_to_trim:-n_to_trim],
                    output[..., n_to_trim:-n_to_trim],
                    atol=1e-1,
                    rtol=1e-4,
                )
